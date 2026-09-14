"""Immutable local turn records, published only after all assets are saved."""

import json
import math
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from image_service import MODEL, Picture, Result, Settings

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Request:
    """One explicit submission, including its selected conversation branch."""

    id: str
    conversation_id: str
    parent_id: str | None
    parent_image: int | None
    prompt: str
    submitted_prompt: str
    settings: Settings
    references: list[Picture]
    mask: Picture | None = None


@dataclass(frozen=True)
class Turn:
    """Completed request metadata; image bytes remain on disk."""

    id: str
    conversation_id: str
    parent_id: str | None
    parent_image: int | None
    prompt: str
    submitted_prompt: str
    settings: dict[str, object]
    images: list[str]
    references: list[str]
    mask: str | None
    created: str
    elapsed: float
    usage: dict[str, object] | None
    request_id: str | None
    model: str = MODEL


def new_id() -> str:
    """Create a filesystem-safe identifier unrelated to user text."""
    return uuid4().hex


def turn_path(root: Path, turn_id: str) -> Path:
    """Resolve a turn directory while rejecting traversal and escaping symlinks."""
    if not re.fullmatch(r"[0-9a-f]{32}", turn_id):
        raise ValueError("Invalid gallery identifier.")
    path = (root / turn_id).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Invalid gallery path.")
    return path


def asset_path(root: Path, turn_id: str, filename: str) -> Path:
    """Restrict asset reads to generated filenames within their turn directory."""
    if not re.fullmatch(r"(?:output|input|mask)-\d+\.(?:png|jpeg|webp)", filename):
        raise ValueError("Invalid gallery asset.")
    directory = turn_path(root, turn_id)
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("Invalid gallery asset path.")
    return path


def load_turn(root: Path, turn_id: str) -> Turn:
    """Load a complete manifest and validate identifiers and file references."""
    directory = turn_path(root, turn_id)
    manifest = (directory / "turn.json").resolve()
    if not manifest.is_relative_to(directory):
        raise ValueError("Invalid gallery manifest path.")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    turn = Turn(**payload)
    if turn.id != turn_id or turn.model != MODEL or not turn.images:
        raise ValueError("Invalid gallery record.")
    turn_path(root, turn.conversation_id)
    if turn.parent_id is not None:
        turn_path(root, turn.parent_id)
    if (
        not isinstance(turn.prompt, str)
        or not isinstance(turn.submitted_prompt, str)
        or not isinstance(turn.created, str)
        or not isinstance(turn.images, list)
        or not isinstance(turn.references, list)
        or not isinstance(turn.elapsed, (int, float))
        or not math.isfinite(turn.elapsed)
        or turn.elapsed < 0
        or (turn.usage is not None and not isinstance(turn.usage, dict))
        or (
            turn.parent_image is not None
            and (type(turn.parent_image) is not int or turn.parent_image < 0)
        )
    ):
        raise ValueError("Invalid gallery metadata.")
    Settings(**payload["settings"]).validate()
    for filename in [*turn.images, *turn.references, *([turn.mask] if turn.mask else [])]:
        if not asset_path(root, turn_id, filename).is_file():
            raise ValueError("A saved image is missing.")
    return turn


def list_turns(root: Path) -> tuple[list[Turn], int]:
    """List valid records newest first, reporting damaged records separately."""
    turns: list[Turn] = []
    damaged = 0
    # ponytail: scan local manifests; add a SQLite index if gallery size makes this slow.
    for manifest in root.glob("*/turn.json"):
        if manifest.parent.name.startswith("."):
            continue
        try:
            turns.append(load_turn(root, manifest.parent.name))
        except OSError, ValueError, TypeError, KeyError:
            damaged += 1
    return sorted(turns, key=lambda turn: turn.created, reverse=True), damaged


def ancestry(turns: list[Turn], active_id: str | None) -> list[Turn]:
    """Follow only the selected branch, detecting incomplete or cyclic history."""
    by_id = {turn.id: turn for turn in turns}
    branch: list[Turn] = []
    seen: set[str] = set()
    while active_id:
        if active_id in seen or active_id not in by_id:
            raise ValueError(
                "Conversation history is incomplete. Start a new conversation with this image."
            )
        seen.add(active_id)
        turn = by_id[active_id]
        branch.append(turn)
        active_id = turn.parent_id
    return list(reversed(branch))


def save_turn(root: Path, request: Request, result: Result) -> Turn:
    """Atomically publish a complete turn; retrying a local save is idempotent."""
    destination = turn_path(root, request.id)
    if destination.exists():
        return load_turn(root, request.id)
    if not result.images:
        raise ValueError("Cannot save an empty result.")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=root) as temporary:
        staging = Path(temporary)

        def write_images(images: list[Picture], prefix: str) -> list[str]:
            names = []
            for i, picture in enumerate(images):
                name = f"{prefix}-{i}.{picture.format}"
                asset_path(root, request.id, name)
                (staging / name).write_bytes(picture.data)
                names.append(name)
            return names

        images = write_images(result.images, "output")
        references = write_images(request.references, "input")
        masks = write_images([request.mask], "mask") if request.mask else []
        turn = Turn(
            request.id,
            request.conversation_id,
            request.parent_id,
            request.parent_image,
            request.prompt,
            request.submitted_prompt,
            asdict(request.settings),
            images,
            references,
            masks[0] if masks else None,
            datetime.now(UTC).isoformat(),
            result.elapsed,
            result.usage,
            result.request_id,
        )
        (staging / "turn.json").write_text(json.dumps(asdict(turn), indent=2), encoding="utf-8")
        staging.rename(destination)
    return turn
