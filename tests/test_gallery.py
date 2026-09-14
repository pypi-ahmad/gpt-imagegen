"""Local persistence and selected-branch history survive fresh reads."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_service import image_bytes

from gallery_store import (
    Request,
    ancestry,
    asset_path,
    list_turns,
    load_turn,
    new_id,
    save_turn,
    turn_path,
)
from image_service import Result, Settings, read_picture


def request(parent: str | None = None) -> Request:
    """Return a complete submission fixture."""
    picture = read_picture(image_bytes())
    return Request(
        new_id(),
        new_id(),
        parent,
        0 if parent else None,
        "original",
        "submitted",
        Settings(),
        [picture],
        read_picture(image_bytes(alpha=True), mask=True),
    )


def result() -> Result:
    return Result([read_picture(image_bytes())], 2.5, {"total_tokens": 3}, "request-id")


def test_persist_reopen_and_idempotent_save(tmp_path: Path) -> None:
    submission = request()
    turn = save_turn(tmp_path, submission, result())
    assert load_turn(tmp_path, turn.id) == turn
    assert save_turn(tmp_path, submission, result()) == turn
    assert turn.prompt == "original" and turn.submitted_prompt == "submitted"
    assert turn.mask == "mask-0.png" and turn.references == ["input-0.png"]
    assert asset_path(tmp_path, turn.id, turn.images[0]).read_bytes() == result().images[0].data
    assert list_turns(tmp_path) == ([turn], 0)
    assert not list(tmp_path.glob(".pending-*"))


def test_branches(tmp_path: Path) -> None:
    root = save_turn(tmp_path, request(), result())
    child = save_turn(tmp_path, request(root.id), result())
    sibling = save_turn(tmp_path, request(root.id), result())
    turns, _ = list_turns(tmp_path)
    assert ancestry(turns, child.id) == [root, child]
    assert ancestry(turns, sibling.id) == [root, sibling]
    assert ancestry(turns, None) == []
    for records, active in [([], root.id), ([replace(root, parent_id=root.id)], root.id)]:
        with pytest.raises(ValueError, match="incomplete"):
            ancestry(records, active)


def test_failures_do_not_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    submission = request()

    def fail_write(*args: object, **kwargs: object) -> int:
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_bytes", fail_write)
        with pytest.raises(OSError):
            save_turn(tmp_path, submission, result())
    assert list_turns(tmp_path) == ([], 0)
    assert not (tmp_path / submission.id).exists()
    assert save_turn(tmp_path, submission, result()).id == submission.id
    with pytest.raises(ValueError, match="empty"):
        save_turn(tmp_path, request(), Result([], 0, None, None))


@pytest.mark.parametrize("mutation", ["json", "id", "model", "images", "missing", "prompt", "path"])
def test_damaged_records_are_skipped(tmp_path: Path, mutation: str) -> None:
    turn = save_turn(tmp_path, request(), result())
    manifest = tmp_path / turn.id / "turn.json"
    payload = json.loads(manifest.read_text())
    if mutation == "json":
        manifest.write_text("broken json")
    elif mutation == "missing":
        asset_path(tmp_path, turn.id, turn.images[0]).unlink()
    else:
        values = {
            "id": new_id(),
            "model": "different",
            "images": [],
            "prompt": 3,
            "path": ["../../outside.png"],
        }
        payload["images" if mutation == "path" else mutation] = values[mutation]
        manifest.write_text(json.dumps(payload))
    assert list_turns(tmp_path) == ([], 1)


def test_incomplete_and_invalid_paths(tmp_path: Path) -> None:
    (tmp_path / ".pending-interrupted").mkdir()
    (tmp_path / ".pending-interrupted" / "turn.json").write_text("{}")
    assert list_turns(tmp_path) == ([], 0)
    with pytest.raises(ValueError):
        turn_path(tmp_path, "../escape")
    with pytest.raises(ValueError):
        asset_path(tmp_path, new_id(), "../escape.png")


def test_save_without_mask_or_references(tmp_path: Path) -> None:
    turn = save_turn(tmp_path, replace(request(), mask=None, references=[]), result())
    assert turn.mask is None and turn.references == []
