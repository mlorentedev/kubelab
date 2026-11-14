---
tags: [spec, verification, templates]
created: "2026-11-13"
id: "AI-016-hermes-nan-capabilities"
type: spec-verification
status: active
owner: manu
---

# Verification - AI-016-hermes-nan-capabilities

## Evidence

- [x] **AC1 — one measured catalog.** `tests/test_open_webui_models.py`, `tests/test_open_webui_rag.py`, `tests/test_hermes_config.py` and `tests/test_agent_stack_role.py` prove both consumers use `apps.services.ai.nan.models`. Live catalog measurement on 2026-11-13: 11 chat completions passed, `minimax-h3` returned 403 and is excluded, embedding returned 4096 dimensions, and rerank returned two results. Final focused run: **206 passed**.
- [x] **AC2 — pinned capabilities work.** `tests/test_hermes_config.py` proves the v0.22.1 keys and `${NAN_API_KEY}` reference without a literal credential. Live one-shot chat returned exactly `AI016-CHAT-OK`. Through `tools.vision_tools.vision_analyze_tool`, configured `qwen3.6` identified a synthetic solid-red PNG as `Red`. Through the pinned Kokoro adapter then Whisper adapter, a 28,077-byte sample saying `Hermes speech verification` returned `Hermes Speech Verificación.`. These were direct Hermes adapter proofs, not Slack voice-message round trips.
- [x] **AC3 — bounded selectable image generation.** `tests/test_hermes_nan_image_provider.py` covers both models, one shared counter, locking, month reset, corruption refusal and no backend call at exhaustion. The live registry reported `registered=True, available=True`. One `NaNImageGenProvider.generate(..., aspect_ratio='square')` call materialized a `flux-2-klein` image at `1024x1024`, returned 49 remaining and moved `$HERMES_HOME/cache/nan-image-quota.json` from `used=0` to `used=1` for `2026-11`. A later read after gateway recreations still returned `used=1`. No second live image was spent after the response-label unit correction.
- [x] **AC4 — memory and sandbox writes recover.** Live `MemoryStore` add/patch/remove returned success for all three operations and advanced `MEMORY.md` mtime. The memories directory was `0755`, UID/GID `10000:10000` in the gateway; the memory file remained `0600`. After removing the synthetic entry the file was byte-identical to `HEAD`. A real `DockerEnvironment` with rendered `docker_run_as_host_user: true` wrote as `10000:10000`; the host observed `534287:534287`. The rest of the vault stayed read-only, the synthetic file was removed, and namespace-aware git status contained no memory changes or locks.
- [x] **AC5 — reproducible delivery.** Final consecutive provisions: `changed=2, failed=0`, then **`changed=0, failed=0`**. Open WebUI returned `{"status":true}` and Hermes was `running`, `oom=false`. `make test` finished with **10,457 passed, 96 skipped**; `make lint` passed Ruff and formatting; `make lint-ansible` parsed all 26 playbooks. `docs/runbooks/hermes-kubelab.md` records the operating boundaries and sibling follow-ups.

## Test status

| Check | Observed result |
|---|---|
| `poetry run pytest -q tests/test_agent_stack_role.py tests/test_open_webui_models.py tests/test_open_webui_rag.py tests/test_hermes_config.py tests/test_hermes_curator_judge.py tests/test_hermes_digest.py tests/test_hermes_sidecar.py tests/test_hermes_memory_permissions.py tests/test_hermes_nan_image_provider.py` | 206 passed |
| `make test` | 10,457 passed, 96 skipped, 30 warnings; 78% total coverage |
| `make lint` | All checks passed; 168 files already formatted |
| `make lint-ansible` | All 26 playbooks parse |
| `make sync-platform-json` plus committed-manifest test | Manifest regenerated; drift test passed |
| `git diff --check` | No whitespace errors |
| `make provision NODE=ace2 ENV=prod TAGS=agent_stack` (final run 1) | `ok=232 changed=2 failed=0` |
| Same command (final run 2) | `ok=232 changed=0 failed=0` |

`dotf spec check` is not a subcommand in the installed CLI; the feature-to-AC mapping was reviewed manually against `features.json` and this evidence. `make lint-ansible` is syntax parsing, not a claim that a whole-repository `ansible-lint` run is clean. The full suite initially exposed stale generated-manifest metadata and test-created bytecode in the role; both were corrected and the complete suite was rerun rather than inferred from targeted retries.

## Live smoke details

| Probe | Observed behavior |
|---|---|
| Hermes chat | Exit 0; answer `AI016-CHAT-OK`; one user turn, no tool calls |
| Vision selection | `deepseek-v4-flash` answered `White` for the red PNG and was rejected; `qwen3.6` answered `Red` before and after it became the configured model |
| Speech | Kokoro generated non-empty MP3 audio; Whisper returned success with the expected words |
| Image registry and quota | Provider initially was not enabled; after the fix it registered, one flux request succeeded, and the persistent counter remained at one |
| Memory | Add/patch/remove succeeded; mtime advanced; no synthetic content or git diff remained |
| Sandbox and mounts | UID/GID 10000 inside, 534287 outside; clone `0711`, zone and memories `0755`; non-zone vault mount not writable |
| Service health | Open WebUI healthy on `100.64.0.5:3080`; Hermes running and not OOM-killed |

## Decisions made during implementation

- **User backends require opt-in.** The first live image probe made no NaN request and consumed no quota because discovery returned `None`. Pinned `plugins_discovery.gate_manifest` auto-loads only bundled backends. Rendering `plugins.enabled: [image_gen/nan]`, plus a live-registry provision assertion, fixed the actual boundary. The inherited OpenAI transport label is normalized to `provider: nan` in results.
- **Vision is pinned by semantic proof, not endpoint status.** `deepseek-v4-flash` returned a successful but incorrect description; the catalog now pins `qwen3.6` with a regression comment and test.
- **Traverse-only vault root.** A `0700` clone owned by the sync user blocked sandbox UID 10000 before it reached the nested writable mount. `0711` allows traversal without listing; zone/memories/proposals stay `0755` and memory files keep their existing modes.
- **Hermes image size remains the pinned adapter's contract.** Open WebUI uses the catalog's `512x512`; v0.22.1 maps square to `1024x1024`. NaN accepted that size in the single live request, so no upstream provider rewrite was added merely to force a different size.
- **Transient analyzer defect ticketed.** A final provision attempt hit `http.client.IncompleteRead` while streaming a GitHub lessons archive. This pre-existing missing retry/integrity boundary is kubelab#3517 (AI-032), with root cause, fix options and acceptance criteria. The diagnosed provision retry succeeded; AI-016 does not claim to fix the analyzer.
- **Sibling work remains separate.** #2175 liveness, #2299's remaining fallback probes and #2189 inbound ACLs are not completed by this change. Telegram/email and risk-tiered autonomous operations remain staged under #2364.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? no: the two new operational diagnostics and their exact repairs are retained in `docs/runbooks/hermes-kubelab.md`; no separate reusable lesson is needed beyond that runbook.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: this implements ADR-068 and existing NaN/vault boundaries without changing architecture.
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: all evidence and fixes are currently specific to this Hermes/v0.22.1 deployment.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AI-016-hermes-nan-capabilities/` -> `specs/archive/AI-016-hermes-nan-capabilities/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
