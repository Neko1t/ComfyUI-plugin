# Implementation plan

## Objective

Implement the approved specification in docs/specification.md with a uv environment and a Git commit after each completed, verified task. No external publication or paid generation without the required service credentials/authorization.

## Tasks

1. [complete] Persist approved specification, research corrections, plan and initialize Git.
2. [complete] Install/configure uv, create .venv, lock dependencies and bootstrap MIT package.
3. [complete] Verify the latest stable ComfyUI API and current VividAI protocol; record baseline and integration design.
4. [complete] Implement credentials, persistent node records and bounded recent-material queue; verify and commit.
5. [complete] Implement VividAI upload/stream/reconnect/download client; verify against a mock HTTP service and commit.
6. [in_progress] Implement four V3 nodes, native media conversion and lazy execution; verify and commit.
7. [pending] Implement frontend credential entry, dynamic models, expandable model rules, history and regeneration controls; verify and commit.
8. [pending] Add examples, install documentation and end-to-end verification; fix findings and commit.

## Constraints

- Respect existing user files and do not commit secrets, environments, runtime caches or development ComfyUI checkout.
- Use real current API sources to verify library-specific code; independently batch reads, sequence mutations and commits.
- Do not silently create a second remote task after an ambiguous submission.
- Only delete files owned by the plugin cache, after resolving and checking their paths.
- Do not claim real-provider or cross-platform checks that were not run.

## Errors / resolutions

- Initial shell inspection did not find uv; install it during task 2.
