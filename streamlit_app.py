"""Local image generation, conversational edits, and saved gallery."""

import asyncio
import math
import os
from pathlib import Path
from typing import cast

import streamlit as st

from gallery_store import (
    DATA_DIR,
    Request,
    Turn,
    ancestry,
    asset_path,
    list_turns,
    new_id,
    save_turn,
)
from image_service import (
    MODEL,
    Format,
    Quality,
    Result,
    Settings,
    build_prompt,
    generate,
    read_picture,
    safe_error,
)


@st.cache_data(ttl=5, max_entries=4)
def gallery_index(root: str) -> tuple[list[Turn], int]:
    """Cache only local metadata, never paid generation requests."""
    return list_turns(Path(root))


def select_image(turn_id: str | None = None, image_index: int = 0) -> None:
    """Select a branch before widgets render and clear one-turn attachments."""
    st.session_state.active_id = turn_id
    st.session_state.active_image = image_index
    st.session_state.upload_epoch += 1
    st.session_state.view = "Create"
    st.session_state.error_message = None


def persist_result() -> None:
    """Retry disk persistence without making another API request."""
    request, result = st.session_state.unsaved
    try:
        turn = save_turn(DATA_DIR, request, result)
    except OSError, ValueError:
        st.session_state.error_message = (
            "Images generated, but saving failed. Download them below or retry saving."
        )
    else:
        st.session_state.unsaved = None
        st.session_state.active_id = turn.id
        st.session_state.active_image = 0
        st.session_state.error_message = None
        gallery_index.clear()


def show_image(turn: Turn, index: int, *, context: str, busy: bool) -> None:
    """Render one saved image with download and branch-selection actions."""
    try:
        path = asset_path(DATA_DIR, turn.id, turn.images[index])
        picture = read_picture(path.read_bytes())
    except OSError, ValueError:
        st.warning("This saved image cannot be opened.")
        return
    st.image(picture.data, width="stretch")
    key = f"{context}-{turn.id}-{index}"
    st.caption(f"{picture.width} × {picture.height} · {picture.format.upper()}")
    with st.container(horizontal=True):
        st.download_button(
            "Download",
            picture.data,
            file_name=f"{turn.id}-{index + 1}.{picture.format}",
            mime=picture.mime,
            key=f"download-{key}",
            on_click="ignore",
        )
        st.button(
            "Edit this image",
            key=f"edit-{key}",
            disabled=busy,
            on_click=select_image,
            args=(turn.id, index),
        )


st.set_page_config(page_title="Image studio", page_icon=":material/palette:", layout="wide")
for state_key, initial in {
    "active_id": None,
    "active_image": 0,
    "upload_epoch": 0,
    "pending": None,
    "request_status": None,
    "unsaved": None,
    "error_message": None,
    "view": "Create",
    "last_prompt": "",
}.items():
    st.session_state.setdefault(state_key, initial)

pending: Request | None = st.session_state.pending
busy = pending is not None or st.session_state.unsaved is not None
st.title("Image studio")
st.caption(f"Generate, refine, and keep every version. · {MODEL}")
with st.sidebar:
    st.segmented_control("View", ["Create", "Gallery"], key="view", disabled=busy)
    st.button("New conversation", icon=":material/add:", on_click=select_image, disabled=busy)
    st.caption("Saved locally in this project's data folder.")
    key_present = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    st.caption("API key available" if key_present else "OPENAI_API_KEY missing")

try:
    turns, damaged = gallery_index(str(DATA_DIR))
except OSError:
    turns, damaged = [], 0
    st.warning("The gallery cannot be read. Check access to the data folder.")
if damaged:
    st.warning(f"{damaged} incomplete or damaged gallery record(s) were skipped.")

if st.session_state.error_message:
    st.error(st.session_state.error_message)
    if st.session_state.last_prompt:
        with st.expander("Your last prompt"):
            st.text(st.session_state.last_prompt)

if st.session_state.unsaved is not None:
    unsaved_request, unsaved_result = cast(tuple[Request, Result], st.session_state.unsaved)
    st.warning("Keep this tab open until you save or download these images.")
    for i, picture in enumerate(unsaved_result.images):
        st.image(picture.data, width=400)
        st.download_button(
            "Download unsaved image",
            picture.data,
            file_name=f"{unsaved_request.id}-{i}.{picture.format}",
            mime=picture.mime,
            key=f"unsaved-{i}",
            on_click="ignore",
        )
    st.button("Retry saving locally", on_click=persist_result)

if pending is not None and st.session_state.request_status == "running":
    st.warning(
        "A request was interrupted. It will not be replayed automatically and may have incurred a charge."
    )
    if st.button("Clear interrupted request"):
        st.session_state.pending = None
        st.session_state.request_status = None
        st.rerun()

if st.session_state.view == "Gallery":
    st.subheader("Saved images")
    entries = [(turn, i) for turn in turns for i in range(len(turn.images))]
    if not entries:
        st.info("Your generated images will appear here automatically.")
    else:
        page = int(
            st.number_input(
                "Page", min_value=1, max_value=max(1, math.ceil(len(entries) / 12)), value=1
            )
        )
        columns = st.columns(3)
        for position, (turn, index) in enumerate(entries[(page - 1) * 12 : page * 12]):
            with columns[position % 3], st.container(border=True):
                show_image(turn, index, context="gallery", busy=busy)
                st.caption(turn.created[:19].replace("T", " ") + " UTC")
                st.text(turn.prompt[:200])
                with st.expander("Prompt and settings"):
                    st.text(turn.prompt)
                    st.json(turn.settings)
                    st.caption(turn.model)
else:
    try:
        branch = ancestry(turns, st.session_state.active_id)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    base = None
    if branch:
        try:
            base = read_picture(
                asset_path(
                    DATA_DIR, branch[-1].id, branch[-1].images[st.session_state.active_image]
                ).read_bytes()
            )
        except OSError, ValueError, IndexError:
            st.error("The selected image is unavailable. Start a new conversation.")
            st.stop()
        st.info(
            f"Editing version {len(branch)}, image {st.session_state.active_image + 1}. Select any earlier image to branch."
        )
    with st.expander("Image settings", expanded=not branch):
        columns = st.columns(4)
        quality = columns[0].selectbox(
            "Quality",
            ["auto", "low", "medium", "high"],
            index=2,
            key="quality",
            disabled=busy,
            persist_state="session",
        )
        size_choice = columns[1].selectbox(
            "Size",
            ["1024x1024", "1536x1024", "1024x1536", "auto", "Custom"],
            key="size_choice",
            disabled=busy,
            persist_state="session",
        )
        output_format = columns[2].selectbox(
            "Format",
            ["png", "jpeg", "webp"],
            key="output_format",
            disabled=busy,
            persist_state="session",
        )
        count = columns[3].number_input(
            "Images",
            min_value=1,
            max_value=4,
            value=1,
            key="count",
            disabled=busy,
            persist_state="session",
        )
        size = size_choice
        if size_choice == "Custom":
            left, right = st.columns(2)
            width = left.number_input(
                "Width",
                min_value=16,
                max_value=3840,
                value=1024,
                step=16,
                key="custom_width",
                disabled=busy,
                persist_state="session",
            )
            height = right.number_input(
                "Height",
                min_value=16,
                max_value=3840,
                value=1024,
                step=16,
                key="custom_height",
                disabled=busy,
                persist_state="session",
            )
            size = f"{width}x{height}"
            st.caption(
                "Multiples of 16 · maximum edge 3840 · aspect ratio up to 3:1 · 655,360–8,294,400 pixels"
            )
            if width * height > 2560 * 1440:
                st.warning("Resolutions above 2K are experimental and can cost more.")
        compression = 100
        if output_format != "png":
            compression = st.slider(
                "Compression",
                0,
                100,
                100,
                key="compression",
                disabled=busy,
                persist_state="session",
            )
        st.caption(
            "Each submission uses the API. Larger sizes, higher quality, more images, and references increase usage."
        )
    with st.expander("Reference images and mask"):
        uploads = st.file_uploader(
            "Reference images",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            max_upload_size=50,
            key=f"references-{st.session_state.upload_epoch}",
            disabled=busy,
        )
        if uploads:
            try:
                if len(uploads) + bool(base) > 16:
                    raise ValueError(
                        "At most 16 images are allowed, including the selected version."
                    )
                previews = [read_picture(file.getvalue()).data for file in uploads]
                st.image(previews, width=120)
            except ValueError as exc:
                st.warning(str(exc))
        if base:
            st.caption(
                "The selected version is the first image. Uploaded images are additional references."
            )
        else:
            st.caption(
                "The first uploaded image is the editing base. Maximum 16 images including the selected version."
            )
        mask_upload = st.file_uploader(
            "Optional PNG mask",
            type=["png"],
            max_upload_size=4,
            key=f"mask-{st.session_state.upload_epoch}",
            disabled=busy,
        )
        st.caption(
            "Mask: below 4 MB, matching base dimensions, with fully transparent areas where edits should occur. Applied to this turn only."
        )
        if mask_upload:
            st.warning(
                "Mask-guided edits can produce visible artifacts. Review the generated result carefully."
            )

    for turn in branch:
        with st.chat_message("user"):
            st.text(turn.prompt)
        with st.chat_message("assistant"):
            cols = st.columns(min(2, len(turn.images)))
            for index in range(len(turn.images)):
                with cols[index % len(cols)]:
                    show_image(turn, index, context="chat", busy=busy)
            st.caption(f"Generated in {turn.elapsed:.1f} seconds · Saved locally")
            with st.expander("Request details"):
                st.json(turn.settings)
                if turn.usage:
                    st.json(turn.usage)
                st.text(turn.submitted_prompt)

    prompt = st.chat_input(
        "Describe an image or an edit…",
        key="prompt",
        disabled=busy or not key_present,
        submit_mode="disable",
        max_chars=32_000,
    )
    if not key_present:
        st.info(
            "Configure OPENAI_API_KEY in Windows, then restart the app. The key is read only by the server."
        )
    if isinstance(prompt, str) and prompt and not busy:
        st.session_state.last_prompt = prompt
        try:
            settings = Settings(
                size, cast(Quality, quality), int(count), cast(Format, output_format), compression
            )
            settings.validate()
            references = ([base] if base else []) + [
                read_picture(upload.getvalue()) for upload in uploads
            ]
            mask = read_picture(mask_upload.getvalue(), mask=True) if mask_upload else None
            submitted = build_prompt(prompt, [turn.prompt for turn in branch])
            st.session_state.pending = Request(
                new_id(),
                branch[-1].conversation_id if branch else new_id(),
                branch[-1].id if branch else None,
                st.session_state.active_image if branch else None,
                prompt,
                submitted,
                settings,
                references,
                mask,
            )
        except ValueError as exc:
            st.session_state.error_message = str(exc)
        else:
            st.session_state.request_status = "queued"
            st.session_state.error_message = None
        st.rerun()

if pending is not None and st.session_state.request_status == "queued":
    # Mark consumed before calling OpenAI. A rerun must never replay the request.
    st.session_state.request_status = "running"
    with st.spinner("Creating your images…", show_time=True):
        try:
            result = asyncio.run(
                generate(
                    pending.submitted_prompt, pending.settings, pending.references, pending.mask
                )
            )
        except Exception as exc:
            st.session_state.error_message = safe_error(exc)
        else:
            st.session_state.unsaved = (pending, result)
            persist_result()
        finally:
            st.session_state.pending = None
            st.session_state.request_status = None
            st.session_state.upload_epoch += 1
    st.rerun()
