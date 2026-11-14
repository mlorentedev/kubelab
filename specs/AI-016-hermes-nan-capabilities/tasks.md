---
tags: [spec, tasks, templates]
created: "2026-11-13"
id: "AI-016-hermes-nan-capabilities"
type: spec-tasks
status: active
owner: manu
---

# Tasks - AI-016-hermes-nan-capabilities

> TDD order. Each behavior moves through a watched red failure, minimal implementation and a green rerun. The operator-assigned branch already exists: `feat/hermes-kubelab-tuning`.

## Setup

- [x] Branch created from `origin/master`: `feat/hermes-kubelab-tuning`; worktree initially clean.
- [x] `proposal.md` is complete and acceptance criteria are testable.
- [x] Open questions resolved against live NaN, live ace2 and the pinned v0.22.1 source.
- [x] kubelab#2214 self-assigned; separate memory bug filed and self-assigned as kubelab#3485 (AI-031).

## Implementation

### Batch 1 — shared catalog and pinned capability wiring

- [x] [P] [AC1] Extend `tests/test_open_webui_models.py` and `tests/test_hermes_config.py` with the measured 11-model chat catalog, non-chat capabilities, shared embedding/rerank declarations and rejection of `minimax-h3`. Run `poetry run pytest -q tests/test_open_webui_models.py tests/test_hermes_config.py`; expect RED because the shared `apps.services.ai.nan.models` catalog and Hermes capability sections do not exist.
- [x] [AC1] Move the NaN catalog to `apps.services.ai.nan.models` in `infra/config/values/common.yaml`; pass it through `infra/ansible/playbooks/provision-ace2.yml` and `tests/test_agent_stack_role.py`; render Open WebUI chat, STT, TTS, images and RAG from it.
- [x] [AC2] Add failing assertions for Hermes `auxiliary.vision`, `stt.openai`, `tts.openai`, `image_gen.openai`, NaN base URL and `${NAN_API_KEY}` without a literal secret; watch the focused tests fail before editing the template.
- [x] [AC2] Render those pinned-v0.22.1 sections from the shared catalog in `hermes-config.yaml.j2`, preserving role-owned sections and current fallback/cron/delegation behavior. Rerun batch-1 tests to green.

### Batch 2 — real shared monthly image guard

- [x] [P] [AC3] Add `tests/test_hermes_nan_image_provider.py`: allow the first request, share one counter across flux and qwen, refuse request 51 without a backend call, reset on a new UTC month, fail closed on corrupt state, and never emit the API key. Run it; expect RED because the provider module is absent.
- [x] [AC3] Add the role-owned `image_gen/nan` provider and manifest, wrapping the pinned OpenAI provider with a locked, atomic, persistent 50-request counter. Mount it read-only, enable the plugin, and point `image_gen.provider` at it. Keep the OpenAI endpoint/model selection contract and `max_parallel_requests: 1`.
- [x] [AC3] Run the new provider tests plus batch-1 tests to green; inspect that no secret appears in rendered config or provider logs.

### Batch 3 — AI-031 ownership, writable paths and stale locks

- [x] [P] [AC4] Update memory/ownership tests: require `docker_run_as_host_user: true`, computed rootless subuid ownership and `0755` memories, writable cache/zone declarations, stopped-writer stale-lock cleanup and existing ignore behavior. Run `poetry run pytest -q tests/test_hermes_config.py tests/test_hermes_digest.py tests/test_hermes_memory_permissions.py tests/test_hermes_vault_sync.py`; observed RED on the old `01777` mode and missing sandbox user setting.
- [x] [AC4] Implement the minimal changes in `hermes-config.yaml.j2`, `agent_stack` defaults and `vault_zone.yml`: effective UID/GID 10000 ownership, no sticky bit, writable cache/zone paths, and safe stale-lock removal. Keep managed skills read-only and namespace-aware vault sync intact.
- [x] [AC4] Rerun the focused ownership tests to green, then all agent-stack tests; 3 stale contract failures were corrected and the final full repository suite passed 10,457 tests.

### Batch 4 — live verification and knowledge

- [x] [AC2] [AC3] [AC4] Provision ace2 through `make provision NODE=ace2 ENV=prod TAGS=agent_stack`; final consecutive runs reported `changed=2, failed=0` then `changed=0, failed=0`, with no credentials printed.
- [x] [AC2] Configured qwen3.6 identified the red test image; Kokoro generated 28,077 bytes and Whisper transcribed `Hermes Speech Verificación.` through the pinned Hermes adapters (not a Slack voice round trip).
- [x] [AC3] One flux image materialized at 1024x1024, counter advanced 0 to 1 with 49 remaining, and later provider/gateway recreations preserved `used=1`.
- [x] [AC4] Memory add/patch/remove succeeded and advanced mtime; real sandbox UID/GID 10000 mapped to host 534287, memories are `0755`, and namespace-aware git status has no memory locks or diff.
- [x] [AC5] Updated `docs/runbooks/hermes-kubelab.md` with the measured catalog, qwen3.6 vision pin, shared quota/reserve, user-backend enablement, traverse-only vault root, ownership repair and verification boundaries. Analyzer retry debt is #3517; #2175/#2299/#2189 remain separate.
- [x] [AC5] Focused tests passed 206; `make test` passed 10,457 with 96 skipped; Ruff/format and 26 playbook parses passed; `git diff --check` was clean. Outputs are in `verification.md` and `features.json`.

## Closing

- [x] Every acceptance criterion is covered by tests and a non-vacuous `features.json` command.
- [x] Diff is within scope and production executable LOC is reported in the PR.
- [x] `verification.md` filled with observed evidence; no unproven Slack or idempotency claim.
- [x] Independent adversarial review proposed (`dotf spec review AI-016-hermes-nan-capabilities`) before archive; do not self-review or archive from this implementing session.
- [x] Draft PR opened while iterating, marked ready only when checks and live evidence are complete; no auto-merge or force-push.
- [ ] `dotf pr triage-queue` rerun and the new PR's checks/review output dispositioned before completion is claimed.
- [ ] Session ends with `/handoff`.

## Machine-readable features

The sibling `features.json` maps AC1–AC5 to executable focused-test commands. Live evidence is recorded in `verification.md`; no state is marked passing without observed command output.
