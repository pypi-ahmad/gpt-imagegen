"""Exercise submissions, reruns, branching, gallery, and saving failures in Streamlit."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_service import image_bytes

import gallery_store
import image_service
from image_service import Result, read_picture

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, AsyncMock]:
    monkeypatch.setattr(gallery_store, "DATA_DIR", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    mock = AsyncMock(return_value=Result([read_picture(image_bytes())], 1.2, None, None))
    monkeypatch.setattr(image_service, "generate", mock)
    at = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not at.exception
    return at, mock


def test_generate_rerun_edit_and_gallery(app: tuple[AppTest, AsyncMock]) -> None:
    at, api = app
    at.chat_input[0].set_value("A blue circle").run()
    assert not at.exception
    assert api.await_count == 1
    first = at.session_state.active_id
    at.selectbox(key="quality").select("high").run()
    assert api.await_count == 1
    at.chat_input[0].set_value("Make it green").run()
    assert not at.exception
    assert api.await_count == 2
    args = api.call_args.args
    assert "A blue circle" in args[0] and "Make it green" in args[0]
    assert len(args[2]) == 1
    assert at.session_state.active_id != first
    at.button(key=f"edit-chat-{first}-0").click().run()
    assert at.session_state.active_id == first
    at.session_state.view = "Gallery"
    at.run()
    assert not at.exception
    assert api.await_count == 2
    assert len(at.get("download_button")) == 2
    at.button(key=f"edit-gallery-{first}-0").click().run()
    assert at.session_state.view == "Create"


def test_validation_custom_and_new_conversation(app: tuple[AppTest, AsyncMock]) -> None:
    at, api = app
    at.selectbox(key="size_choice").select("Custom").run()
    at.number_input(key="custom_width").set_value(16).run()
    at.chat_input[0].set_value("circle").run()
    assert at.error and not at.exception
    assert api.await_count == 0
    at.number_input(key="custom_width").set_value(3840).run()
    at.number_input(key="custom_height").set_value(2160).run()
    assert at.warning
    at.selectbox(key="output_format").select("jpeg").run()
    at.slider(key="compression").set_value(80).run()
    at.chat_input[0].set_value("circle").run()
    assert not at.exception
    assert api.call_args.args[1].compression == 80
    next(button for button in at.button if button.label == "New conversation").click().run()
    assert at.session_state.active_id is None


def test_api_failure_does_not_retry(app: tuple[AppTest, AsyncMock]) -> None:
    at, api = app
    api.side_effect = RuntimeError("private response body")
    at.chat_input[0].set_value("circle").run()
    assert at.error and not at.exception
    assert "private" not in at.error[0].value
    at.run()
    assert api.await_count == 1
    assert at.session_state.pending is None


def test_save_failure_and_local_retry(
    app: tuple[AppTest, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    at, api = app
    original = gallery_store.save_turn

    def fail_save(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(gallery_store, "save_turn", fail_save)
    at.chat_input[0].set_value("circle").run()
    assert not at.exception and at.session_state.unsaved is not None
    assert at.get("download_button")
    monkeypatch.setattr(gallery_store, "save_turn", original)
    at.run()
    next(button for button in at.button if button.label == "Retry saving locally").click().run()
    assert not at.exception and at.session_state.unsaved is None
    assert api.await_count == 1


def test_missing_key(app: tuple[AppTest, AsyncMock], monkeypatch: pytest.MonkeyPatch) -> None:
    at, api = app
    monkeypatch.delenv("OPENAI_API_KEY")
    at.run()
    assert at.chat_input[0].disabled
    assert api.await_count == 0


def test_upload_validation_and_one_turn_mask(
    app: tuple[AppTest, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    at, api = app
    base = image_bytes()
    mask = image_bytes(alpha=True)

    def upload(label: str, **kwargs: object) -> object:
        if not str(kwargs["key"]).endswith("-0"):
            return [] if label == "Reference images" else None
        return (
            [SimpleNamespace(getvalue=lambda: base)]
            if label == "Reference images"
            else SimpleNamespace(getvalue=lambda: mask)
        )

    monkeypatch.setattr(st, "file_uploader", upload)
    at.run()
    at.chat_input[0].set_value("Edit this uploaded image").run()
    assert not at.exception and api.await_count == 1
    assert len(api.call_args.args[2]) == 1 and api.call_args.args[3].data == mask
    at.chat_input[0].set_value("Another edit").run()
    assert api.call_args.args[3] is None
    assert not at.exception


def test_interrupted_request_never_replays(app: tuple[AppTest, AsyncMock]) -> None:
    from test_gallery import request

    at, api = app
    at.session_state.pending = request()
    at.session_state.request_status = "running"
    at.run()
    assert at.warning and not at.exception and api.await_count == 0
    next(
        button for button in at.button if button.label == "Clear interrupted request"
    ).click().run()
    assert at.session_state.pending is None and api.await_count == 0


def test_gallery_after_new_session(app: tuple[AppTest, AsyncMock]) -> None:
    at, api = app
    at.chat_input[0].set_value("A circle").run()
    fresh = AppTest.from_file(str(APP), default_timeout=15)
    fresh.session_state.view = "Gallery"
    fresh.run()
    assert not fresh.exception and len(fresh.get("download_button")) == 1
    assert api.await_count == 1
