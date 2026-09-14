"""Explicit, paid end-to-end verification: generate, edit, then mask-edit.

Must not run automatically: unlike tests/, this hits the real OpenAI API and
costs money, so it only executes behind the explicit --run flag. Read
image_service.py for what each request actually sends.
"""

import argparse
import asyncio
import json
from io import BytesIO

from PIL import Image, ImageDraw

from gallery_store import DATA_DIR, Request, asset_path, load_turn, new_id, save_turn
from image_service import MODEL, Picture, Settings, build_prompt, generate, read_picture, safe_error


def expected_center_color(picture: Picture, phase: str) -> bool:
    """Check this synthetic circle task; this is not a general image-quality score."""
    with Image.open(BytesIO(picture.data)) as source:
        with source.convert("RGB") as image:
            pixel = image.getpixel((picture.width // 2, picture.height // 2))
    assert isinstance(pixel, tuple)
    channel = {"generate": 2, "edit": 0, "mask": 1}[phase]
    return pixel[channel] > max(value for i, value in enumerate(pixel) if i != channel) + 30


async def verify() -> None:
    """Make exactly three requests and save evidence through the normal gallery."""
    conversation = new_id()
    history: list[str] = []
    previous = None
    picture = None
    for phase, prompt in [
        (
            "generate",
            "A flat blue circle centered on a white background. Minimal vector illustration, no text.",
        ),
        ("edit", "Change the circle to red. Keep its position and the white background."),
        ("mask", "Change the circle to green inside the editable area. Keep the white background."),
    ]:
        mask = None
        if phase == "mask" and picture:
            with Image.new("RGBA", (picture.width, picture.height), (255, 255, 255, 255)) as image:
                ImageDraw.Draw(image).rectangle(
                    (
                        picture.width // 8,
                        picture.height // 8,
                        picture.width * 7 // 8,
                        picture.height * 7 // 8,
                    ),
                    fill=(0, 0, 0, 0),
                )
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                mask = read_picture(buffer.getvalue(), mask=True)
        request = Request(
            new_id(),
            conversation,
            previous.id if previous else None,
            0 if previous else None,
            prompt,
            build_prompt(prompt, history),
            Settings(quality="low"),
            [picture] if picture else [],
            mask,
        )
        try:
            result = await generate(
                request.submitted_prompt, request.settings, request.references, mask
            )
            turn = save_turn(DATA_DIR, request, result)
            reopened = load_turn(DATA_DIR, turn.id)
            picture = read_picture(
                asset_path(DATA_DIR, reopened.id, reopened.images[0]).read_bytes()
            )
            assert (picture.width, picture.height) == (1024, 1024)
            assert reopened.parent_id == (previous.id if previous else None)
        except Exception as exc:
            print(
                json.dumps({"phase": phase, "passed": False, "error": safe_error(exc)}), flush=True
            )
            raise SystemExit(1) from None
        visual_passed = expected_center_color(picture, phase)
        print(
            json.dumps(
                {
                    "phase": phase,
                    "api_and_persistence_passed": True,
                    "visual_check_passed": visual_passed,
                    "model": MODEL,
                    "turn_id": turn.id,
                    "elapsed_seconds": round(result.elapsed, 2),
                    "usage": result.usage,
                    "request_id": result.request_id,
                }
            ),
            flush=True,
        )
        if not visual_passed:
            print(
                "The image did not match the test's expected center color. Inspect the saved result.",
                flush=True,
            )
            raise SystemExit(1)
        history.append(prompt)
        previous = turn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make three paid OpenAI image requests.")
    if parser.parse_args().run:
        asyncio.run(verify())
    else:
        parser.print_help()
