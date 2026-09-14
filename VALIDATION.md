# Validation (2026-09-09)

## Automated checks

- 80 pytest tests passed, including Streamlit AppTest submissions, branch selection, fresh-session gallery reads, uploads, one-turn masks, duplicate-request prevention, local-save recovery, and seven Windows launcher checks.
- Core coverage: 98.64% across the API and gallery modules.
- Ruff lint, Ruff formatting, and ty type checks passed.
- Tests inspect the real SDK's multipart serialization using a local mock transport. The base image and alpha mask are separate fields; PNG conversion preserves the base image's content.

## Real API requests

All three used `gpt-image-2-2026-04-21`, one 1024×1024 image, and low quality. All returned valid images and reopened successfully from disk. Exactly three paid requests were made.

| Request | Duration | Input/output tokens | Visual result | Saved turn |
| --- | --- | --- | --- | --- |
| Generate blue circle | 19.26 s | 23 / 196 | Blue center; passed | `272809c74d56499cafe394b85ea52d0a` |
| Edit circle to red | 14.39 s | 1106 / 196 | Red center; passed | `782070494d8d4826bf940425412b9abe` |
| Mask-edit circle to green | 27.93 s | 1126 / 196 | Black rectangle inside the mask; visual check failed | `82a7a2424b3a4f62aeff8b879baff481` |

The mask has the required alpha channel: transparent center and opaque exterior. It matches the 1024×1024 base image. The SDK serialization test confirms correct file separation and alpha preservation. The cause of the generated artifact is unresolved; mask support is implemented, but reliable visual mask behavior is not established by this run. Original inputs, mask, output, prompts, request IDs, and token usage remain in `data/<turn-id>/` for inspection.

The live-check script now distinguishes API/persistence success from the synthetic visual criterion and exits unsuccessfully when the expected center color is missing. This criterion is specific to these circle prompts, not a general semantic-accuracy score.

## Running app

The local page and `/_stcore/health` returned HTTP 200; health response was `ok`.

Visual browser inspection could not run because the browser-control tool reported no available browsers. UI behavior was checked with AppTest; actual browser layout and download interactions remain unverified.

## Windows launcher

`launch.cmd` configures port 8507 and uses PowerShell to stop any listening process on that port before launching Streamlit. Automated checks execute its actual cleanup command with mocked Windows process operations: free port, duplicate listeners, access denied, persistent occupancy, and query failure. Batch-level checks verify missing-uv and failed-sync handling from another working directory, including paths with spaces.

The proposed live disposable-listener/restart test was blocked by the execution environment's policy before running. Therefore real process replacement, browser opening, and app health on 8507 remain unverified. Read-only inspection afterward confirmed the existing server still listening on 8501 (PID 35596) and no listeners on 8507 or 8508. No additional paid image requests were made.
