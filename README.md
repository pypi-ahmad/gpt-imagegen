# Image studio

A local Streamlit application for generating images and refining them through
conversational edits, using the OpenAI Images API. Requests always target the
pinned model `gpt-image-2-2026-04-21`. Generated images, prompts, and settings
are saved to the local filesystem so a conversation can be resumed after a
restart.

## Requirements

Taken from `pyproject.toml` and `.python-version`:

- Python `>=3.14.7`
- [`uv`](https://docs.astral.sh/uv/) for dependency locking and running the app
- Runtime dependencies: `openai>=3.10.0`, `pillow>=12.3.0`, `streamlit>=1.63.0`
- Dev dependencies (for linting/testing): `pytest>=9.1.1`, `pytest-cov>=7.1.0`,
  `ruff>=0.16.6`, `ty>=0.0.79`

The Windows launcher (`launch.cmd`) is Windows-only: it uses `cmd.exe` batch
syntax and calls `powershell.exe` to free a TCP port. The manual commands
below (`uv sync`, `uv run streamlit run ...`) have no Windows-specific code
and should run on any OS `uv` and Streamlit support, but this has not been
verified on non-Windows platforms in this repository.

## Setup and run

### Windows, with automatic port cleanup

```powershell
.\launch.cmd
```

This script (verified in `launch.cmd`):
1. Changes to the project directory.
2. Fails with an error if `uv` is not on `PATH`.
3. Runs `uv sync --locked`.
4. Force-stops any process listening on TCP port 8507, including unrelated
   applications (see "Known limitations").
5. Runs `uv run --no-sync streamlit run streamlit_app.py --server.port=8507 --server.address=127.0.0.1 --server.headless=false`.

On failure at any step it prints `Launcher failed. Review the error above.`
and pauses the console (`pause`) instead of closing it.

### Manual, any OS `uv` supports

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

This does not clear an occupied port. The server address, port (8507), and
upload size limit come from `.streamlit/config.toml`, so both launch paths
serve on `http://127.0.0.1:8507` unless that file is changed.

## Usage

Verified against `streamlit_app.py`:

1. Create: enter a prompt in the chat input. Adjust quality (auto/low/
   medium/high, default medium), size (presets, `auto`, or custom), output
   format (png/jpeg/webp), image count (1-4), and compression (jpeg/webp
   only) under **Image settings**.
2. Refine: submitting again while a result is selected edits that image.
   **Edit this image** on any saved image selects it and branches the
   conversation from there. Earlier prompts in the branch are sent as
   context, and the latest prompt takes precedence over earlier ones.
3. References and mask: upload PNG, JPEG, or WebP files as additional
   references (up to 16 images total, including the selected base, each
   under 50 MB). An optional PNG mask (under 4 MB, alpha channel, at least
   one fully transparent pixel, matching the base image's dimensions) marks
   the area to edit. References and the mask apply to one submission only.
4. Gallery: successful turns save automatically under `data/`. Switch to
   the **Gallery** view to browse, download, or resume editing any saved
   image after a restart.

Custom size constraints, enforced in `image_service.Settings.validate()`:
multiples of 16 per edge, at most 3840 pixels per edge, aspect ratio up to
3:1, and total area between 655,360 and 8,294,400 pixels.

## Configuration

- `OPENAI_API_KEY` (environment variable, required): read at request time
  via `os.environ` in `image_service.py`. If it is missing or blank, image
  requests are rejected before any network call, and `streamlit_app.py`
  disables the prompt input. There is no `.env` file support in the code,
  so the key must be set as a real process/OS environment variable, and the
  terminal or host must be restarted after changing it so the new value is
  inherited.
- `.streamlit/config.toml`: sets `server.address = "127.0.0.1"`,
  `server.port = 8507`, `server.maxUploadSize = 50` (MB), and
  `browser.gatherUsageStats = false`.
- No other configuration files (`.env.example`, JSON/YAML config, etc.) exist
  in this repository.

## Repository map

| Path | Contents |
| --- | --- |
| `streamlit_app.py` | Streamlit UI entry point: view state, request submission, gallery browsing |
| `image_service.py` | Input/output validation and the OpenAI Images API request/response handling |
| `gallery_store.py` | Local persistence: saving, loading, and path safety for turns under `data/` |
| `live_check.py` | Manual, explicitly invoked script that makes real (paid) API requests end to end |
| `launch.cmd` | Windows launcher: environment sync, port cleanup, app start |
| `tests/` | Pytest suite (`test_service.py`, `test_gallery.py`, `test_app.py`, `test_launcher.py`) |
| `data/` | Local gallery storage created at runtime, excluded from Git via `.gitignore` |
| `.streamlit/config.toml` | Streamlit server/browser configuration |
| `knowledge/` | Agent-authored, human-unreviewed project notes in Open Knowledge Format; see `knowledge/index.md` |
| `pyproject.toml`, `uv.lock`, `.python-version` | Python project manifest, locked dependencies, pinned interpreter version |
| `docs/` | `ARCHITECTURE.md`, `TECHNICAL.md`, `RUNBOOK.md`, `CONTRIBUTING.md` (this documentation set) |

## Running tests

```powershell
uv run pytest -q
```

Verified in `pyproject.toml`: `testpaths = ["tests"]`, and `addopts` runs with
coverage on `image_service` and `gallery_store`, failing under 91% coverage.
The Windows launcher tests in `tests/test_launcher.py` are skipped outside
`win32` (`pytestmark = pytest.mark.skipif(sys.platform != "win32", ...)`).
Tests mock the OpenAI client and use temporary directories, so running them
does not call the real API or cost money.

Lint and type checks referenced by `pyproject.toml` and used in this
project's own validation history (see `VALIDATION.md`):

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

A separate, explicitly paid check exists outside the test suite:

```powershell
uv run python live_check.py --run
```

`live_check.py` makes three real sequential API requests (generate, edit,
mask-edit) and must be run intentionally, not as part of routine testing.

## Known limitations

Visible directly in code, comments, or the repository's own validation
report:

- Port cleanup is destructive to unrelated processes. `launch.cmd` stops any
  process listening on TCP port 8507, not just a previous instance of this
  app.
- No automatic retry. `image_service.generate()` calls the OpenAI client
  with `max_retries=0`. A timeout or interruption may have already been
  billed, and the code does not resubmit automatically.
- Gallery listing is a linear directory scan. `gallery_store.list_turns()`
  carries the comment `# ponytail: scan local manifests; add a SQLite index
  if gallery size makes this slow.` There is no index, so listing cost
  grows with the number of saved turns.
- Mask-guided edits are not guaranteed pixel-exact. `VALIDATION.md` (dated
  2026-09-09) records a live mask-edit request that returned a valid, saved
  image containing an unexpected black rectangle instead of the requested
  edit; the cause was not resolved in that report.
- No logging is implemented. No module in this repository imports Python's
  `logging` package, so the only diagnostic output is what `streamlit run`
  and `launch.cmd` print to the console. (Stray files
  `data/server.stdout.log` and `data/server.stderr.log` exist in this tree,
  but nothing in the code writes them; they appear to be leftover manual
  output redirection, not an application feature.)
- Single local user, single API key. There is no authentication, multi-user
  support, or per-user API key handling; the app is designed to run locally
  for one user.
- No CI is configured. `.github/` contains only `copilot-instructions.md`;
  there are no GitHub Actions workflows in this repository.

## Further reading

- `docs/ARCHITECTURE.md`: request/data flow, main types, external systems
- `docs/TECHNICAL.md`: stack rationale, invariants, error handling, persistence
- `docs/RUNBOOK.md`: start/stop, diagnosing failures, log locations
- `docs/CONTRIBUTING.md`: local dev setup and checks before committing
- `knowledge/index.md`: draft, agent-authored architecture/runbook/validation notes (human-unreviewed; current source and tests take precedence over conflicts)

## Sources

- [Pinned model and supported endpoints](https://developers.openai.com/api/docs/models/gpt-image-2)
- [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [Image editing parameters](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
