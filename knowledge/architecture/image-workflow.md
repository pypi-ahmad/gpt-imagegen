---
type: Architecture
title: Image workflow
description: How the local Streamlit app generates, edits, and persists image conversations.
status: draft
generated:
  by: okf-skill/0.2
  at: 2026-09-09T14:32:54.8699074+05:30
sources:
  - id: streamlit-ui
    resource: ../../streamlit_app.py
  - id: image-service
    resource: ../../image_service.py
  - id: gallery-store
    resource: ../../gallery_store.py
---

# Image workflow

Draft knowledge derived from implementation, not human-reviewed guidance. Recheck current source before changing behavior.

## Requests and model

The Streamlit entry point provides Create and Gallery views. Requests use exactly `gpt-image-2-2026-04-21` through the OpenAI Images API; conversational editing does not introduce a separate chat model. Without reference images, the service calls image generation. With references, it calls image editing.[^streamlit-ui][^image-service]

The service targets `https://api.openai.com/v1`, reads the inherited `OPENAI_API_KEY`, uses a 600-second request timeout, and disables SDK retries. Its defaults are one medium-quality 1024×1024 PNG. Settings, decoded images, reference counts, and masks are validated before the API call. A mask must be a PNG below 4 MB with an alpha channel containing fully transparent edit pixels, and must match the first reference image's dimensions.[^image-service]

## Conversation branches

Selecting an earlier output chooses the base image and its ancestor branch. Follow-up requests send that image first, additional uploads as references, and the branch's earlier prompts as context. The latest prompt takes precedence over conflicting earlier instructions. Combined prompts exceeding 32,000 characters are rejected rather than silently truncated. Reference uploads and masks apply to one submission.[^streamlit-ui][^image-service]

## Persistence and recovery

Completed turns live under the project's `data/<turn-id>/` directory. A turn contains output images, original reference images, an optional mask, and a `turn.json` manifest recording prompts, parent selection, settings, model, timestamp, elapsed time, usage, and request ID when available. Files are staged in a temporary directory and published together by renaming it. Retrying a save for an existing turn ID loads that saved turn instead of writing another version.[^gallery-store]

Gallery loading ignores pending directories and reports damaged records separately. Ancestry traversal rejects missing or cyclic history. The UI tracks queued/running requests to avoid duplicate API calls on reruns and retains unsaved results in session state for downloads or a local-save retry. That retry does not make a new image request. Session-only results can be lost on server restart; download them before restarting.[^gallery-store][^streamlit-ui]

See [local launch](../runbooks/local-launch.md) for operation and [validation status](../concepts/validation-status.md) for evidence limits.

[^streamlit-ui]: [Streamlit UI and submission/recovery logic](../../streamlit_app.py).
[^image-service]: [Image validation, prompt construction, and API client](../../image_service.py).
[^gallery-store]: [Local manifests, branch traversal, and atomic publication](../../gallery_store.py).
