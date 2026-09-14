---
type: Runbook
title: Local launch
description: Start and stop the Windows app while understanding port cleanup and data preservation.
status: draft
generated:
  by: okf-skill/0.2
  at: 2026-09-09T14:32:54.8699074+05:30
sources:
  - id: project-readme
    resource: ../../README.md
  - id: windows-launcher
    resource: ../../launch.cmd
  - id: streamlit-config
    resource: ../../.streamlit/config.toml
  - id: project-metadata
    resource: ../../pyproject.toml
---

# Local launch

Draft operating notes. Launcher behavior below is implemented; live restart and browser-opening verification remain incomplete. See [validation status](../concepts/validation-status.md).

## Prerequisites

Use Windows with `uv` on PATH. The project uses Python 3.14.7 and locked dependencies managed by uv. Image inference runs on OpenAI, not a local GPU. Configure `OPENAI_API_KEY` in the Windows environment and restart the terminal or host after changes so the app inherits it. Never put the key in this bundle, source files, or a copied environment file.[^project-readme][^project-metadata]

## Launch with automatic port cleanup

Double-click `launch.cmd`, or run this from the project folder:

```powershell
.\launch.cmd
```

The launcher switches to its own directory, checks for uv, and runs `uv sync --locked` before cleanup. It then **force-stops any process listening on TCP port 8507**, including unrelated apps. Relaunching can interrupt requests and lose unsaved work. It does not target other ports or delete saved gallery files.[^windows-launcher]

Cleanup enumerates listening owners, rechecks ownership before stopping each PID, and waits up to five seconds for the port to become free. Missing uv, setup failure, cleanup errors, or persistent occupancy abort the launch and pause the console. The launcher does not elevate privileges automatically.[^windows-launcher]

After cleanup it invokes Streamlit through uv, explicitly binding to `127.0.0.1:8507` with browser opening enabled. Keep the console attached for logs; press Ctrl+C to stop the app.[^windows-launcher]

## Manual launch without process cleanup

From the project folder:

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

The project configuration defaults to `http://127.0.0.1:8507`. This manual command does not clear an occupied port; unlike the launcher, it does not explicitly override environment-level Streamlit settings. The configured server is local-only, with a 50 MB upload setting and usage telemetry disabled.[^project-readme][^streamlit-config]

## Gallery backup and interrupted work

Back up the entire `data` directory to retain completed conversations, images, references, and masks. Download any unsaved results before restarting. If saving fails, use **Retry saving locally** instead of submitting the prompt again. A new submission is a new paid request; an interrupted or timed-out request may already have incurred a charge.[^project-readme]

[^project-readme]: [Setup, workflows, and recovery instructions](../../README.md).
[^windows-launcher]: [Windows launcher and exact port-cleanup behavior](../../launch.cmd).
[^streamlit-config]: [Project server and browser defaults](../../.streamlit/config.toml).
[^project-metadata]: [Python requirement and application dependencies](../../pyproject.toml).
