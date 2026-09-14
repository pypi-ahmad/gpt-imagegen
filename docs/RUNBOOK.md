# Runbook

This app is a single local Streamlit process. There is no separate database,
queue, or background worker to operate.

## Start

Windows, with automatic port cleanup:

```powershell
.\launch.cmd
```

Manual, any OS `uv` supports (does not clear a busy port):

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

Either path serves at `http://127.0.0.1:8507` per `.streamlit/config.toml`.

## Stop

Press `Ctrl+C` in the console running the launcher or `streamlit run`. The
process must be attached to that console; there is no separate stop script
or service manager in this repository.

If the app was left running or crashed without releasing port 8507, the next
`launch.cmd` run stops it automatically as part of its port-cleanup step
(see "Known limitations" in the README: this stops *any* process on that
port, not only a previous instance of this app).

## Logs

No dedicated log file is implemented: no module in this repository imports
Python's `logging` package. The only diagnostic output is whatever
`streamlit run` and `launch.cmd` print to the attached console (startup
messages, tracebacks, the launcher's own `echo`/`Write-Host` lines).

Two files, `data/server.stdout.log` and `data/server.stderr.log`, exist in
this tree, but nothing in the current code writes them. They are not
produced by `launch.cmd`, `streamlit_app.py`, or any other module here, and
should be treated as leftovers from a manual run rather than a documented
log location.

## Diagnosing failures

Failure messages below are copied from the source that raises them, so they
can be matched directly against what appears on screen.

**Launcher (`launch.cmd`), before the app starts:**

| Message | Cause | Where |
| --- | --- | --- |
| `ERROR: uv is not installed or is not on PATH.` | `where uv` failed | `launch.cmd` |
| (output of `uv sync --locked`, then) `Launcher failed. Review the error above.` | dependency sync failed | `launch.cmd` |
| `ERROR: Cannot clear port 8507. <reason>` | `Stop-Process` failed (e.g. access denied) or the port was still occupied after a 5-second poll | `launch.cmd`'s embedded PowerShell block |

Any of these leaves the console open via `pause` instead of closing it.

**Missing credential, before any request is sent:**

| Message | Cause | Where |
| --- | --- | --- |
| `OPENAI_API_KEY is missing. Restart the host after configuring the Windows variable.` | the environment variable is unset or blank when `generate()` is called | `image_service.py` |

The UI also disables the chat input outright when the key is absent
(`streamlit_app.py`, `key_present` check).

**API request failures**, mapped by `image_service.safe_error()` to avoid
echoing raw response bodies:

| Situation | User-facing message |
| --- | --- |
| `openai.AuthenticationError` | OpenAI authentication failed. Check OPENAI_API_KEY and restart the app if it changed. |
| `openai.PermissionDeniedError` / `openai.NotFoundError` | This key cannot use the pinned image model. Check project access and organization verification. |
| `openai.RateLimitError` | OpenAI rate limit or quota reached. Check billing and limits before trying again. |
| `openai.APITimeoutError` | OpenAI timed out. The request may have completed and incurred a charge. Retry manually only. |
| `openai.APIConnectionError` | Could not connect to OpenAI. Check your connection; the request was not retried automatically. |
| `openai.BadRequestError` | OpenAI rejected the prompt, image, or settings. Content restrictions may apply. |
| anything else | The request failed. No automatic retry was attempted; previous images remain available. |

None of these are retried automatically (`max_retries=0`); a resubmission
from the UI is a new, separately billed request.

**Local save failures**, after a successful (already billed) API call:

| Message | Cause | Where |
| --- | --- | --- |
| `Images generated, but saving failed. Download them below or retry saving.` | writing to `data/<turn-id>/` raised `OSError`/`ValueError` | `streamlit_app.py`, `persist_result()` |

The UI keeps the generated images in `st.session_state.unsaved` with a
download button, and offers **Retry saving locally**, which calls
`save_turn()` again without making another API request.

**Damaged or unreadable gallery data:**

| Message | Cause | Where |
| --- | --- | --- |
| `The gallery cannot be read. Check access to the data folder.` | `list_turns()` raised `OSError` | `streamlit_app.py` |
| `<N> incomplete or damaged gallery record(s) were skipped.` | one or more `turn.json` manifests failed validation in `load_turn()` | `streamlit_app.py` / `gallery_store.py` |
| `This saved image cannot be opened.` / `A saved image is missing.` | an individual asset file failed to decode or was not found | `streamlit_app.py` |
| `Conversation history is incomplete. Start a new conversation with this image.` | `ancestry()` found a missing or cyclic `parent_id` link | `gallery_store.py` |

**Interrupted request on reload:**

| Message | Cause | Where |
| --- | --- | --- |
| `A request was interrupted. It will not be replayed automatically and may have incurred a charge.` | the page reloaded while `request_status == "running"` | `streamlit_app.py` |

A **Clear interrupted request** button resets this state without calling the
API.

## Data recovery

Back up the whole `data/` directory to preserve saved conversations, images,
references, and masks. Interrupted saves leave only a hidden `.pending-*`
staging directory, which `list_turns()` ignores, so it can be deleted
safely.
