"""Exercise validation and the exact API request contract without network calls."""

import asyncio
import base64
from email import policy
from email.parser import BytesParser
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx2
import openai
import pytest
from PIL import Image

import image_service as service
from image_service import MODEL, Settings, build_prompt, generate, read_picture, safe_error


def image_bytes(
    fmt: str = "PNG", size: tuple[int, int] = (32, 32), *, alpha: bool = False
) -> bytes:
    """Create a small valid test image."""
    with Image.new("RGBA" if alpha else "RGB", size, (0, 0, 0, 0) if alpha else "blue") as image:
        buffer = BytesIO()
        image.save(buffer, format=fmt)
        return buffer.getvalue()


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, SimpleNamespace]:
    """Replace all remote calls and isolate the credential presence check."""
    response = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(image_bytes()).decode())],
        usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 7}),
        _request_id="request-test",
    )
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=response)
    client.images.edit = AsyncMock(return_value=response)
    context = AsyncMock()
    context.__aenter__.return_value = client
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    monkeypatch.setattr(service.os, "environ", {"OPENAI_API_KEY": "unit-test-placeholder"})
    return client, factory, response


@pytest.mark.parametrize(
    "size", ["auto", "1024x1024", "1536x1024", "1024x1536", "3840x2160", "2160x3840", "2048x2048"]
)
def test_valid_sizes(size: str) -> None:
    Settings(size=size).validate()


@pytest.mark.parametrize(
    "values",
    [
        {"size": "1x1"},
        {"size": "1025x1024"},
        {"size": "4000x2048"},
        {"size": "3840x512"},
        {"size": "3840x3840"},
        {"size": "bad"},
        {"size": "0x1024"},
        {"size": "1024X1024"},
        {"count": 0},
        {"count": 5},
        {"count": True},
        {"count": 1.5},
        {"quality": "max"},
        {"output_format": "gif"},
        {"compression": -1},
        {"compression": 101},
        {"compression": True},
    ],
)
def test_invalid_settings(values: dict) -> None:
    with pytest.raises(ValueError):
        Settings(**values).validate()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_picture_formats(fmt: str) -> None:
    picture = read_picture(image_bytes(fmt))
    assert picture.format == fmt.lower()
    assert picture.mime == f"image/{fmt.lower()}"
    assert picture.width == picture.height == 32


@pytest.mark.parametrize(
    "data,mask",
    [
        (b"", False),
        (b"not an image", False),
        (image_bytes("GIF"), False),
        (image_bytes(), True),
        (image_bytes("WEBP", alpha=True), True),
        (b"x" * 4_000_000, True),
        (b"x" * 50_000_000, False),
    ],
    ids=[
        "empty",
        "invalid-bytes",
        "gif",
        "no-alpha",
        "webp-mask",
        "oversized-mask",
        "oversized-image",
    ],
)
def test_bad_images(data: bytes, mask: bool) -> None:
    with pytest.raises(ValueError):
        read_picture(data, mask=mask)


def test_bomb_and_opaque_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    data = image_bytes()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match="safely"):
        read_picture(data)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(ValueError, match="safely"):
        read_picture(data)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10000)
    with Image.new("RGBA", (32, 32), "white") as image:
        buffer = BytesIO()
        image.save(buffer, "PNG")
    with pytest.raises(ValueError, match="transparent"):
        read_picture(buffer.getvalue(), mask=True)


def test_animation_rejected() -> None:
    buffer = BytesIO()
    with Image.new("RGB", (8, 8), "red") as first, Image.new("RGB", (8, 8), "blue") as second:
        first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100)
    with pytest.raises(ValueError, match="still image"):
        read_picture(buffer.getvalue())


def test_prompt_history_and_limits() -> None:
    assert build_prompt(" draw a cat ", []) == " draw a cat "
    combined = build_prompt("green", ["blue", "red"])
    assert combined.index("blue") < combined.index("red") < combined.index("green")
    assert len(build_prompt("a" * 32000, [])) == 32000
    invalid: list[tuple[str, list[str]]] = [("  ", []), ("a" * 32001, []), ("b", ["a" * 32000])]
    for prompt, history in invalid:
        with pytest.raises(ValueError):
            build_prompt(prompt, history)


def test_generation_contract(api: tuple) -> None:
    client, factory, _ = api
    result = asyncio.run(generate("blue circle", Settings(count=4), []))
    kwargs = client.images.generate.call_args.kwargs
    assert kwargs["model"] == MODEL
    assert kwargs["n"] == 4
    assert kwargs["output_compression"] is openai.omit
    assert "response_format" not in kwargs and "input_fidelity" not in kwargs
    assert result.images and result.usage == {"total_tokens": 7}
    assert result.elapsed >= 0 and result.request_id == "request-test"
    assert factory.call_args.kwargs == {
        "base_url": "https://api.openai.com/v1",
        "max_retries": 0,
        "timeout": 600.0,
    }
    client.images.edit.assert_not_called()


def test_edit_order_mask_conversion_and_compression(api: tuple) -> None:
    client, _, _ = api
    first, second = read_picture(image_bytes("JPEG")), read_picture(image_bytes("WEBP"))
    mask = read_picture(image_bytes(alpha=True), mask=True)
    asyncio.run(
        generate("edit", Settings(output_format="jpeg", compression=75), [first, second], mask)
    )
    kwargs = client.images.edit.call_args.kwargs
    assert kwargs["model"] == MODEL
    assert kwargs["image"][0][0] == "reference-0.png"
    assert kwargs["image"][1][1] == second.data
    assert kwargs["mask"][1] == mask.data
    assert kwargs["output_compression"] == 75
    client.images.generate.assert_not_called()


def test_edit_without_mask(api: tuple) -> None:
    client, _, response = api
    response.usage = None
    result = asyncio.run(generate("edit", Settings(), [read_picture(image_bytes())]))
    assert result.usage is None
    assert client.images.edit.call_args.kwargs["mask"] is openai.omit


def test_preflight_does_not_call_api(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, factory, _ = api
    picture = read_picture(image_bytes())
    mask = read_picture(image_bytes(alpha=True), mask=True)
    for references, selected_mask in [
        ([picture] * 17, None),
        ([], mask),
        ([read_picture(image_bytes(size=(16, 16)))], mask),
    ]:
        with pytest.raises(ValueError):
            asyncio.run(generate("edit", Settings(), references, selected_mask))
    monkeypatch.setattr(service.os, "environ", {})
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        asyncio.run(generate("generate", Settings(), []))
    factory.assert_not_called()


@pytest.mark.parametrize(
    "value", [None, "!not-base64!", base64.b64encode(b"invalid image").decode()]
)
def test_invalid_api_image(api: tuple, value: str | None) -> None:
    api[2].data = [SimpleNamespace(b64_json=value)]
    with pytest.raises(ValueError):
        asyncio.run(generate("generate", Settings(), []))


def test_empty_api_output(api: tuple) -> None:
    api[2].data = None
    with pytest.raises(ValueError, match="no images"):
        asyncio.run(generate("generate", Settings(), []))


@pytest.mark.parametrize(
    "error_type,status,fragment",
    [
        (openai.AuthenticationError, 401, "authentication"),
        (openai.PermissionDeniedError, 403, "cannot use"),
        (openai.NotFoundError, 404, "cannot use"),
        (openai.RateLimitError, 429, "quota"),
        (openai.BadRequestError, 400, "rejected"),
        (openai.InternalServerError, 500, "failed"),
    ],
)
def test_safe_errors(error_type: type, status: int, fragment: str) -> None:
    response = MagicMock(status_code=status, headers={})
    error = error_type("SENSITIVE RESPONSE BODY", response=response, body=None)
    assert fragment in safe_error(error)
    assert "SENSITIVE" not in safe_error(error)


def test_connection_errors_and_validation() -> None:
    assert "timed out" in safe_error(openai.APITimeoutError(request=MagicMock()))
    assert "connect" in safe_error(openai.APIConnectionError(request=MagicMock()))
    assert safe_error(ValueError("Invalid size")) == "Invalid size"
    assert "SENSITIVE" not in safe_error(RuntimeError("SENSITIVE"))


def test_sdk_multipart_keeps_base_and_mask_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inspect real SDK serialization without sending credentials or images remotely."""
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    original_factory = openai.AsyncOpenAI
    base = read_picture(image_bytes("JPEG"))
    mask = read_picture(image_bytes(alpha=True), mask=True)
    captured: dict[str, bytes] = {}

    async def receive(request: httpx2.Request) -> httpx2.Response:
        body = await request.aread()
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + body
        )
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            content = part.get_payload(decode=True)
            assert isinstance(name, str) and isinstance(content, bytes)
            captured[name] = content
        return httpx2.Response(
            200,
            json={"created": 0, "data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]},
        )

    def factory(*, base_url: str, max_retries: int, timeout: float) -> openai.AsyncOpenAI:
        return original_factory(
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(receive)),
        )

    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    asyncio.run(generate("edit the circle", Settings(), [base], mask))
    assert captured["model"].decode() == MODEL
    assert captured["mask"] == mask.data
    base_part = next(value for name, value in captured.items() if name.startswith("image"))
    assert read_picture(base_part).format == "png"
    with Image.open(BytesIO(base_part)) as image:
        pixel = image.getpixel((16, 16))
        assert isinstance(pixel, tuple) and pixel[2] > 200
    with Image.open(BytesIO(captured["mask"])) as image:
        pixel = image.getpixel((16, 16))
        assert isinstance(pixel, tuple) and pixel[3] == 0
