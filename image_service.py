"""Validated requests to the pinned OpenAI image model."""

import base64
import binascii
import os
import re
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

import openai
from PIL import Image, UnidentifiedImageError

MODEL = "gpt-image-2-2026-04-21"
Format = Literal["png", "jpeg", "webp"]
Quality = Literal["auto", "low", "medium", "high"]


@dataclass(frozen=True)
class Settings:
    """Output controls shared by generation and editing."""

    size: str = "1024x1024"
    quality: Quality = "medium"
    count: int = 1
    output_format: Format = "png"
    compression: int = 100

    def validate(self) -> None:
        """Reject unsupported or out-of-range controls before spending tokens."""
        if self.quality not in ("auto", "low", "medium", "high"):
            raise ValueError("Choose auto, low, medium, or high quality.")
        if type(self.count) is not int or not 1 <= self.count <= 4:
            raise ValueError("Choose between 1 and 4 images.")
        if self.output_format not in ("png", "jpeg", "webp"):
            raise ValueError("Choose PNG, JPEG, or WebP output.")
        if type(self.compression) is not int or not 0 <= self.compression <= 100:
            raise ValueError("Compression must be between 0 and 100.")
        if self.size == "auto":
            return
        match = re.fullmatch(r"([1-9]\d{0,3})x([1-9]\d{0,3})", self.size)
        if not match:
            raise ValueError("Size must be WIDTHxHEIGHT or auto.")
        width, height = map(int, match.groups())
        if (
            width % 16
            or height % 16
            or max(width, height) > 3840
            or max(width, height) > 3 * min(width, height)
            or not 655_360 <= width * height <= 8_294_400
        ):
            raise ValueError(
                "Dimensions must be multiples of 16, at most 3840 per edge, "
                "within 3:1, and total 655,360–8,294,400 pixels."
            )


@dataclass(frozen=True)
class Picture:
    """Validated image bytes and their actual media properties."""

    data: bytes
    format: Format
    width: int
    height: int

    @property
    def mime(self) -> str:
        """Return the actual image MIME type."""
        return f"image/{self.format}"


def read_picture(data: bytes, *, mask: bool = False) -> Picture:
    """Decode supported images; reject misleading extensions and invalid masks."""
    limit = 4_000_000 if mask else 50_000_000
    if not data or len(data) >= limit:
        raise ValueError(f"{'Mask' if mask else 'Image'} must be below {limit // 1_000_000} MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                fmt = (image.format or "").lower()
                if fmt not in ("png", "jpeg", "webp"):
                    raise ValueError("Only PNG, JPEG, and WebP images are supported.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Use a still image, not an animated image.")
                image.load()
                if mask and (
                    fmt != "png"
                    or "A" not in image.getbands()
                    or image.getchannel("A").getextrema()[0] != 0
                ):
                    raise ValueError(
                        "Use a PNG mask with an alpha channel and fully transparent edit areas."
                    )
                return Picture(data, fmt, image.width, image.height)
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("Image cannot be decoded safely. Use a valid PNG, JPEG, or WebP.") from exc


def build_prompt(prompt: str, history: list[str]) -> str:
    """Build branch-specific context without silently losing previous instructions."""
    if not prompt.strip():
        raise ValueError("Enter a prompt before generating.")
    submitted = prompt
    if history:
        submitted = (
            "Edit the first image, which is the selected current version. "
            "Additional images are references. Preserve details not requested to change. "
            "Earlier requests provide context; the latest request overrides conflicting earlier requests.\n\n"
            + "\n\n".join(f"Earlier request {i + 1}:\n{text}" for i, text in enumerate(history))
            + f"\n\nLatest request:\n{prompt}"
        )
    if len(submitted) > 32_000:
        raise ValueError(
            "Prompt plus history exceeds 32,000 characters. Start a new conversation using the image as a reference."
        )
    return submitted


@dataclass(frozen=True)
class Result:
    """Decoded API output and measured request metadata."""

    images: list[Picture]
    elapsed: float
    usage: dict[str, object] | None
    request_id: str | None


def safe_error(error: Exception) -> str:
    """Map exceptions to useful messages without revealing HTTP bodies or secrets."""
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, openai.AuthenticationError):
        return (
            "OpenAI authentication failed. Check OPENAI_API_KEY and restart the app if it changed."
        )
    if isinstance(error, (openai.PermissionDeniedError, openai.NotFoundError)):
        return "This key cannot use the pinned image model. Check project access and organization verification."
    if isinstance(error, openai.RateLimitError):
        return "OpenAI rate limit or quota reached. Check billing and limits before trying again."
    if isinstance(error, openai.APITimeoutError):
        return "OpenAI timed out. The request may have completed and incurred a charge. Retry manually only."
    if isinstance(error, openai.APIConnectionError):
        return "Could not connect to OpenAI. Check your connection; the request was not retried automatically."
    if isinstance(error, openai.BadRequestError):
        return "OpenAI rejected the prompt, image, or settings. Content restrictions may apply."
    return "The request failed. No automatic retry was attempted; previous images remain available."


async def generate(
    prompt: str,
    settings: Settings,
    references: list[Picture],
    mask: Picture | None = None,
) -> Result:
    """Call the exact snapshot once using a client scoped to this event loop."""
    settings.validate()
    build_prompt(prompt, [])
    if len(references) > 16:
        raise ValueError("At most 16 reference images are allowed, including the current image.")
    references = [read_picture(picture.data) for picture in references]
    if mask is not None:
        mask = read_picture(mask.data, mask=True)
        if not references or (mask.width, mask.height) != (
            references[0].width,
            references[0].height,
        ):
            raise ValueError("The mask must match the first image's dimensions.")
        with Image.open(BytesIO(references[0].data)) as image:
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            references[0] = read_picture(buffer.getvalue())
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError(
            "OPENAI_API_KEY is missing. Restart the host after configuring the Windows variable."
        )
    start = time.monotonic()
    async with openai.AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=600.0,
    ) as client:
        compression = settings.compression if settings.output_format != "png" else openai.omit
        if references:
            response = await client.images.edit(
                model=MODEL,
                prompt=prompt,
                n=settings.count,
                size=settings.size,
                quality=settings.quality,
                output_format=settings.output_format,
                output_compression=compression,
                image=[
                    (f"reference-{i}.{pic.format}", pic.data, pic.mime)
                    for i, pic in enumerate(references)
                ],
                mask=("mask.png", mask.data, "image/png") if mask else openai.omit,
            )
        else:
            response = await client.images.generate(
                model=MODEL,
                prompt=prompt,
                n=settings.count,
                size=settings.size,
                quality=settings.quality,
                output_format=settings.output_format,
                output_compression=compression,
            )
    images: list[Picture] = []
    try:
        for output in response.data or []:
            if not output.b64_json:
                raise ValueError("OpenAI returned an image without image data.")
            images.append(read_picture(base64.b64decode(output.b64_json, validate=True)))
    except binascii.Error as exc:
        raise ValueError("OpenAI returned invalid image data.") from exc
    if not images:
        raise ValueError("OpenAI returned no images. No automatic retry was attempted.")
    return Result(
        images,
        time.monotonic() - start,
        response.usage.model_dump() if response.usage else None,
        getattr(response, "_request_id", None),
    )
