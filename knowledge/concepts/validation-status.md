---
type: Concept
title: Validation status
description: Recorded validation evidence and remaining limits, not a guarantee of current behavior.
status: draft
generated:
  by: okf-skill/0.2
  at: 2026-09-09T14:32:54.8699074+05:30
sources:
  - id: validation-report
    resource: ../../VALIDATION.md
  - id: launcher-tests
    resource: ../../tests/test_launcher.py
  - id: project-readme
    resource: ../../README.md
  - id: project-metadata
    resource: ../../pyproject.toml
---

# Validation status

This draft summarizes the repository's **2026-09-09 validation report**. Those results are historical evidence, not fresh checks performed while installing OKF, human verification, or guarantees about current model access.[^validation-report]

## Recorded automated evidence

The report records 80 passing pytest tests, 98.64% coverage across the API and gallery modules, and passing Ruff lint, formatting, and ty checks. Coverage is specific to those two modules, not the whole application. The configured minimum is 91%.[^validation-report][^project-metadata]

Seven Windows launcher checks cover missing uv, setup failure, a free port, duplicate listeners, access denial, persistent occupancy, and query failure. Cleanup tests run the launcher's command with mocked Windows process operations; they do not prove that real process replacement succeeds. Batch failure tests use a temporary project path containing spaces and invoke it from another working directory.[^launcher-tests]

## Recorded live API evidence

Three reported requests used `gpt-image-2-2026-04-21`, one low-quality 1024×1024 image each. Generation and a follow-up edit passed the synthetic blue/red circle visual checks. The mask edit returned a valid image and persisted successfully, but contained a black rectangle: **the visual mask check failed**.[^validation-report]

The report describes correct separation of base image and alpha mask in the SDK multipart request. The artifact's cause remains unresolved. API success and valid image bytes must not be represented as successful visual editing, nor generalized into reliable mask behavior.[^validation-report]

## Remaining limits

- Browser layout and actual download interactions were not visually checked because no browser was available.
- The live launcher replacement test was blocked by execution policy. Real listener replacement, browser opening, and health on port 8507 remain unverified in that report.
- The reported successful health response came from the earlier server on port 8501, not proof of the new launcher.

These limits are retained from the report; reread current evidence before relying on them as current status.[^validation-report]

## Rechecking

From the project folder, the documented non-paid checks are:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest -q
```

The separate command `uv run python live_check.py --run` makes paid image requests. Run it only when explicitly authorized, not as part of reading or validating this knowledge bundle.[^project-readme]

[^validation-report]: [Dated validation results and caveats](../../VALIDATION.md).
[^launcher-tests]: [Windows launcher test scenarios and mocks](../../tests/test_launcher.py).
[^project-readme]: [Documented validation commands and paid-check warning](../../README.md).
[^project-metadata]: [Coverage configuration and test tooling](../../pyproject.toml).
