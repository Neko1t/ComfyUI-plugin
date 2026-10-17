# Research findings

## Approved decisions

See docs/specification.md, confirmed by the user on 2026-10-17 after the design interview.

## Protocol correction

Context7's VividAI index is stale. A real browser read of https://vividai.run/docs on 2026-10-17 shows the current public API uses /v1/uploads and /v1/generate, not /v1/videos or /v1/images/generations. Preserve this distinction when implementing.

- GET /v1/models: enabled image/video model IDs only; cached by the service for 10 minutes.
- POST /v1/uploads: kind and mime; returns key, pre-signed PUT url and expiration. PUT Content-Type must exactly match mime.
- Upload lifetime 30 minutes. Images <=20 MB (png/jpeg/webp); video/audio <=40 MB (mp4/webm/mov, mp3/wav/m4a/ogg respectively).
- POST /v1/generate: JSON model/prompt/quality/ratio/duration/refs; prompt <=5000 characters. Range-duration video models require duration. refs are uploaded object keys.
- NDJSON first frame jobId/running; blank heartbeats every 25 seconds; succeeded/failed terminal frames; X-Wait-Seconds up to two hours.
- Reconnect with only jobId. A same-task subscription does not create a new task or repeat charge.
- succeeded has result (30-minute read-only signed URL) and creditsCharged; failed has error/refunded.
- GET /v1/balance is available. Errors use error.code/error.message (4011,4001,4002,4293,5001).

## ComfyUI

- V3 uses io.ComfyNode, define_schema, execute classmethod, ComfyExtension and comfy_entrypoint.
- V1 remains supported; future node features target V3.
- Lazy inputs prevent requesting unnecessary upstream work; returning unused data after eager evaluation does not.
- Native video output is a video object, not a filename string.
- Frontend WEB_DIRECTORY/app.registerExtension can extend widgets and settings; current stable API/source must be checked before implementation.
- Built-in partial execution normally targets output nodes. The approved regenerate button marks the next normal workflow run instead of immediately executing a partial graph.

## Environment

- Workspace initially contains only docs/comfyui-vividai-development.md and is not a Git repository.
- Windows / PowerShell; Git author is configured globally.
- uv was not initially on PATH. Python, Git, Node.js and agent-browser are available.
- Installed uv 0.13.1 through its documented PyPI distribution. Created .venv with uv and CPython 3.13.5; system-site-packages permits the existing host torch installation for integration checks. Project dependencies are separately locked in uv.lock; ordinary installations do not require this development-only sharing option.
- GitHub REST latest-release lookup returned HTTP 403 (rate limit). Git's remote tags work: highest stable tag is v0.41.3, commit 8713616fcc321624e306bbd36be5906203dcb0dc. Checked out that exact tag in ignored .comfyui-dev; comfyui_version.py confirms 0.41.3; frontend pinned to 1.55.17.
- Verified official source: InputImpl.VideoFromFile wraps native VIDEO; VideoInput.save_to supports encoding references; V3 fingerprint_inputs and check_lazy_status are classmethods. HTTPX supports streaming lines/bytes and MockTransport without extra retry middleware.
- Importing the actual ComfyUI source initially failed because comfy_aimdo was absent. Installing the baseline's missing requirements into the project .venv (explicit --python, not Anaconda base) for integration checks. The dry-run without --python selected the active Anaconda environment; it made no changes. All actual installation targets the project venv.
