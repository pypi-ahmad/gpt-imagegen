# Contributing

This repository has no CI configuration (`.github/` contains only
`copilot-instructions.md`, no workflow files) and no documented branch
policy. The expectations below come only from `pyproject.toml` and this
project's own validation history in `VALIDATION.md`.

## Setup

```powershell
uv sync --locked
```

This installs both runtime and dev dependency groups defined in
`pyproject.toml` (`pytest`, `pytest-cov`, `ruff`, `ty`).

## Before committing

Run the checks `pyproject.toml` configures for this project:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q
```

- Ruff is configured with `line-length = 100`, `target-version = "py314"`,
  and lint rule sets `E`, `F`, `I`, `UP`, `B` (`E501` ignored).
- `pytest` runs everything under `tests/` and fails if coverage on
  `image_service` and `gallery_store` drops below 91% (`--cov-fail-under=91`
  in `addopts`).
- Tests mock the OpenAI client and use temporary directories; they do not
  call the real API or cost money. `tests/test_launcher.py` only runs on
  Windows (`skipif(sys.platform != "win32", ...)`).

## Paid checks are opt-in

```powershell
uv run python live_check.py --run
```

This makes real, billed OpenAI requests. Do not run it as part of routine
development or automated checks; run it deliberately, with the
understanding that it will incur API usage.

## Not defined in this repository

Unknown/not present in the tree, so not asserted here: required branch
naming, PR review process, commit message format, versioning/release steps,
or a code of conduct.
