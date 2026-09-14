# Technical notes

## Stack

- Streamlit (`streamlit_app.py`): the entire UI is built with `st.*` calls
  in a single script. There is no separate frontend build step or API
  server.
- `openai` SDK, async client: `image_service.generate()` is an `async def`
  calling `openai.AsyncOpenAI(...)`. `streamlit_app.py` wraps each call in
  `asyncio.run(...)` per request, since Streamlit's own execution model is
  synchronous.
- Pillow (`PIL`): `image_service.read_picture()` uses `Image.open`/`.load()`
  to decode and validate uploads, and explicitly catches Pillow-specific
  `UnidentifiedImageError`, `Image.DecompressionBombError`, and
  `Image.DecompressionBombWarning` (raised as an error via
  `warnings.simplefilter("error", ...)`).
- `uv`: dependency locking and execution, evidenced by `uv.lock`,
  `.python-version`, and `launch.cmd`'s `uv sync --locked` and
  `uv run --no-sync ...`.
- `tempfile.TemporaryDirectory` plus `Path.rename`: `gallery_store.save_turn()`
  writes a complete turn into a private staging directory, then renames it
  into place as one filesystem operation, so a crash mid-write cannot leave
  a half-written turn directory.
- Dev tooling: `pytest` plus `pytest-cov` (coverage gate of
  `--cov-fail-under=91` on `image_service` and `gallery_store`, per
  `pyproject.toml`), `ruff` for lint and format (`target-version = "py314"`,
  `line-length = 100`), and `ty` for type checking.

## Invariants and validation

`image_service.Settings.validate()` raises `ValueError` before any network
request, and checks that:
- `quality` is `auto`, `low`, `medium`, or `high`.
- `count` is an `int` in `1..4` (booleans are explicitly rejected, since
  `type(self.count) is not int`).
- `output_format` is `png`, `jpeg`, or `webp`.
- `compression` is an `int` in `0..100`.
- `size` is `"auto"` or `WIDTHxHEIGHT`, where both are multiples of 16, the
  longer edge is at most 3840, the aspect ratio is at most 3:1, and the
  total area is between 655,360 and 8,294,400 pixels.

`image_service.read_picture()` also raises `ValueError`:
- It rejects empty input and enforces a size ceiling: 4,000,000 bytes for a
  mask, 50,000,000 bytes otherwise.
- Only `png`, `jpeg`, and `webp` are accepted, and multi-frame (animated)
  images are rejected (`n_frames != 1`).
- A mask must be PNG, must have an alpha channel, and must have a minimum
  alpha value of 0 across the image. `getextrema()[0] != 0` failing this
  check means at least one fully transparent pixel is required, or there is
  nothing for the API to edit.

`image_service.build_prompt()`:
- Rejects a blank prompt.
- When there is conversation history, prepends fixed instructions stating
  that the first image is the current version to edit, additional images
  are references, and the latest request overrides conflicting earlier
  ones.
- Rejects a combined prompt (history plus latest) longer than 32,000
  characters rather than truncating it.

`image_service.generate()`:
- Re-validates `settings` and re-runs `build_prompt`'s checks on the
  already-assembled prompt before touching the network. The comment in the
  source notes that the returned string is discarded here; only the
  validation matters.
- Rejects more than 16 total reference images.
- When a mask is supplied, requires it to match the first reference's
  dimensions, and re-encodes that first reference to PNG regardless of its
  original upload format, since the edit API requires a PNG base when a
  mask is used.
- Requires `OPENAI_API_KEY` to be a non-blank environment variable, checked
  right before the request is built, after validation, so a bad request
  never gets that far.
- Calls the SDK with `max_retries=0` and `timeout=600.0`. Failures and
  timeouts are surfaced to the caller rather than retried automatically,
  because a timed-out request may already have been billed.
- Uses `openai.omit`, not `None`, to drop the `output_compression` field
  entirely from the request when the output format is `png`, since PNG has
  no lossy compression setting to send.

`image_service.safe_error()` maps SDK and network exceptions to fixed,
non-sensitive messages (for authentication, permission, rate limit,
timeout, connection, and bad-request cases) and avoids echoing raw
exception text from anything other than a `ValueError` raised by this
codebase's own validation. This is a deliberate boundary against leaking
API response bodies, which could include billing or account detail, into
the UI.

## Persistence

`gallery_store.DATA_DIR` is `<project root>/data`, excluded from Git. Each
turn is stored at `data/<turn-id>/`, where `<turn-id>` is a 32-hex-character
`uuid4().hex` (`new_id()`). Filenames inside a turn directory are
restricted by regex to `(output|input|mask)-<n>.<png|jpeg|webp>` in
`asset_path()`.

`turn_path()` and `asset_path()` both `resolve()` the candidate path and
check `is_relative_to()` the expected root or directory before returning
it, rejecting path traversal.

`save_turn()` is idempotent for a given request id: if `data/<id>/` already
exists, it loads and returns the existing `Turn` instead of writing again,
which guards against a UI retry re-submitting the same request. It writes
to a `tempfile.TemporaryDirectory(prefix=".pending-", dir=root)` and
publishes with a single directory rename. `list_turns()` explicitly skips
any directory whose name starts with `.`, so an interrupted save's staging
directory is never treated as a saved turn.

`load_turn()` treats the on-disk manifest (`turn.json`) as untrusted input:
it re-checks the id, model, and every field's type before constructing a
`Turn`, and re-validates the embedded `Settings`. A manifest that fails any
check, or whose referenced image files are missing, causes that turn to be
skipped (counted as "damaged") rather than raising out of `list_turns()`.

`ancestry()` walks the `parent_id` chain to reconstruct one conversation
branch and raises `ValueError` if it encounters a missing id or a cycle,
rather than looping indefinitely.

`list_turns()` is a linear glob over `root.glob("*/turn.json")`. The
`# ponytail:` comment in the source notes this has no index and would need
one if the gallery grows large.
