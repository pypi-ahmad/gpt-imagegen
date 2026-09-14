# Image studio

A local Streamlit app for creating images and refining them through conversation. All image requests use **`gpt-image-2-2026-04-21`**.

## Run

Double-click **launch.cmd**, or run it from PowerShell:

```powershell
.\launch.cmd
```

The launcher syncs the locked environment with `uv`, force-stops **any process listening on TCP port 8507**, then starts the app and opens your browser. This includes unrelated applications: relaunching can interrupt active requests and lose unsaved work. Saved gallery files are not deleted. Other ports are untouched. Keep the console open; press **Ctrl+C** to stop the app.

If `uv` is missing, setup fails, or the port cannot be cleared, the launcher displays an error and pauses. It does not request administrator privileges automatically.

To start manually without clearing a busy port:

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

Open **http://127.0.0.1:8507**. The server binds to your local machine.

The server reads your existing **`OPENAI_API_KEY`** process environment variable. If you configure or change the Windows variable, restart the terminal/app so it inherits the change. Never paste a key into the app, source files, or `.env` files. The client explicitly targets `https://api.openai.com/v1`.

Python 3.14.7 is pinned. Dependencies are locked with uv. Image inference runs on OpenAI; local GPU packages are unnecessary.

## Use

1. **Create:** Enter a prompt. Choose quality, size, image count, and format under **Image settings**.
2. **Refine:** Send another prompt to edit the selected result. **Edit this image** selects any earlier image and branches from it. The first result is selected by default.
3. **Use references:** Upload PNG, JPEG, or WebP files. With an existing selection, that image comes first; otherwise the first upload is the editing base. References apply to the next submission only.
4. **Apply a mask:** Upload a PNG with an alpha channel, below 4 MB, matching the base image's dimensions. Fully transparent areas indicate where to edit. Masks guide generation; they do not guarantee pixel-exact preservation. Masks apply to one turn only.
5. **Keep results:** Successful turns save automatically. Open **Gallery** to browse, download, or continue editing after restarting the app.

**New conversation** starts fresh without deleting earlier work. Each branch sends its ancestor instructions plus the selected image; the latest instruction takes precedence. Requests exceeding 32,000 characters including history are rejected instead of silently truncated.

### Output controls

| Control | Options |
| --- | --- |
| Quality | Auto, low, medium (default), high |
| Images per request | 1–4; default 1 |
| Size | Square, landscape, portrait, auto, custom; default 1024×1024 |
| Format | PNG (default), JPEG, WebP |
| Compression | 0–100 for JPEG/WebP; default 100 |

Custom dimensions must be multiples of 16, at most 3840 pixels per edge, within a 3:1 aspect ratio, and total 655,360–8,294,400 pixels. Resolutions above the documented 2K threshold are experimental. Up to 16 input images are supported, including the selected base; each must be below 50 MB. Limits are checked on the server as well as in widgets.

## Gallery and recovery

`data/<turn-id>/` contains output images, reference images, an optional mask, and `turn.json`. Metadata includes the exact model, original and submitted prompts, parent image, settings, timestamp, elapsed time, request ID, and usage when returned. Save the whole `data` folder when backing up conversations. It is excluded from Git.

Completed turn directories are published atomically. Interrupted temporary directories are ignored. Damaged or incomplete records are reported and skipped. Original uploads and previous versions are preserved.

Requests are never retried automatically. After a timeout or interruption, OpenAI may still have processed and billed the request. A manual resubmission is a new paid request. If disk saving fails, keep the tab open: download the images or choose **Retry saving locally**, which does not call OpenAI again.

Every submission uses your API quota. Larger images, higher quality, additional outputs, and references can increase usage. The app shows returned token usage rather than estimating a dollar charge.

## Validation

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q
```

Tests use temporary galleries and mocked API calls; they make no paid requests. They cover API parameters, input validation, masks, branch history, persistence, damaged records, reruns, and local-save recovery. Coverage is enforced above 90% for the API and storage modules.

For an explicit **paid** end-to-end check:

```powershell
uv run python live_check.py --run
```

This makes three sequential requests: generate, edit, and mask-edit, each requesting one low-quality 1024×1024 image. Results are saved in the normal gallery and reopened to validate persistence. It stops on failure and never retries automatically.

The check also tests the expected center color for its synthetic circle prompts. The initial generation and follow-up edit passed. The mask request returned and saved a valid image, but it contained a black rectangle, so its visual result failed. The SDK sends the base and alpha mask as separate, correct multipart fields; the cause of the artifact is unresolved. See [validation results](VALIDATION.md). Browser visual testing requires a connected browser and was unavailable in this session.

## Sources

- [Pinned model and supported endpoints](https://developers.openai.com/api/docs/models/gpt-image-2)
- [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [Image editing parameters](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
