---
id: "AI-016-hermes-nan-capabilities"
type: spec
status: implementing
created: "2026-11-13"
issue: "mlorentedev/kubelab#2214"
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "Operator explicitly assigned AI-016 and AI-031 in this session; existing active specs are unrelated and cannot be archived by the implementing session. (15 active, limit 10, 2026-11-13)"
---

# AI-016: Hermes NaN capabilities and memory-writer repair

## Why

<!-- from issue #2214: AI-016: hermes-kubelab knows and uses the NaN models our tier serves (vision, speech, images) -->

Hermes and Open WebUI currently read different model declarations, and Hermes can use only its default and scheduled/delegated chat routes. The operator needs one measured NaN catalog for chat, vision, speech, images, embeddings and reranking, with image use bounded so the agent cannot silently consume Open WebUI's allowance. At the same time, kubelab#3485 (`AI-031`) records a live memory outage: mixed gateway/sandbox ownership and a sticky memories directory prevent atomic renames and leave stale locks, so restoring the model capabilities must not leave the agent unable to remember what it learns.

## What

After this change, `apps.services.ai.nan.models` in `common.yaml` is the single NaN capability catalog consumed by both Open WebUI and Hermes. Open WebUI offers exactly the 11 chat models measured accessible on 2026-11-13 (excluding `minimax-h3`, which returned 403), while Hermes renders pinned-`v0.22.1` keys for native/auxiliary vision, Whisper STT, Kokoro TTS and OpenAI-compatible image generation. `flux-2-klein` is the default image model and `qwen-image-2.1` the declared alternative; embeddings and reranking remain Open WebUI's RAG routes because the pinned Hermes image has no corresponding config contract.

A role-owned, read-only NaN image provider wraps the pinned OpenAI provider with a persistent, locked, shared monthly counter. Hermes may make at most 50 image requests per UTC month across both models, reserving the other 50 of NaN's documented shared 100-request allowance for Open WebUI. A corrupt counter fails closed and the provider never writes secrets into config.

The role also repairs AI-031: terminal sandboxes run as UID/GID 10000, the memories mirror loses its sticky bit and gains effective gateway ownership with mode 0755, writable cache paths and the vault zone are declared, and stale memory locks are cleaned safely while remaining git-ignored. Managed skills and configuration stay read-only.

## Out of scope

- Upgrading Hermes to v0.23.x. `hermes curator lock`, keychain-backed browser-vault storage and the v0.23 ownership changes were reviewed but are not needed for these routes; the pinned v0.22.1 source is the contract.
- Enabling `minimax-h3`, adding a per-request model-switching tool, or adding Hermes embedding/rerank config keys that the pinned image does not implement.
- The gateway liveness decision (#2175), the remaining pinned-turn and no-Slack-negative fallback probes (#2299), and the Headscale inbound ACL tightening (#2189). These are sibling tickets, not hidden work in this PR.
- Making managed skills writable, weakening sandbox network isolation, or modifying upstream Hermes source in a forked image.

## Risks / open questions

Resolved before implementation:

- **Measured catalog.** Live `/v1/models` returned 18 entries on 2026-11-13. One-token-style completion probes succeeded for 11 chat models; `minimax-h3` returned 403 and is excluded. Embedding returned 4096 dimensions and rerank returned two results.
- **Shared image quota.** NaN's current documentation says 100 requests/member/month **shared by both image models**, correcting the older per-model assumption. The local counter cannot see Open WebUI calls, so the 50/50 split is deliberate headroom, not an exact global count; NaN is still the final global limiter.
- **Pinned credential routes.** v0.22.1 expands `${NAN_API_KEY}` in config. STT/TTS require the expanded `api_key` beside the custom `base_url`; using only an OpenAI-named environment variable would lose NaN's custom base URL in the STT resolver. No secret is rendered by Ansible tests or written literally into config.
- **Effective ownership.** Host UID 10000 is not the gateway's rootless subuid. The role computes the subuid mapped to container UID/GID 10000 from `agent_stack_agent_subid_start` and enforces that numeric owner on the host; inside the gateway this is 10000:10000. Namespace-aware sync remains necessary for 0600 atomic writes.
- **F5 evidence.** Live caches are writable but mode 0777; the role will make ownership and mode deterministic. The separately managed skills mount must remain read-only by design.
- **Live evidence boundary.** Provider/API smoke checks are codified and run where possible. A result that does not exercise Slack's inbound adapter will be reported as such rather than claimed as a Slack end-to-end proof.

## Acceptance criteria

- [x] **AC1. One measured catalog.** Open WebUI and Hermes render only declared NaN models for their respective capabilities; the chat allowlist contains the 11 accessible models and excludes `minimax-h3`. Tests fail on an undeclared or inaccessible model and on drift between the two consumers.
- [x] **AC2. Hermes capabilities work through the pinned contract.** Rendered config wires the catalog's vision model, `whisper`, `kokoro` (`ef_dora`) and image endpoint with `${NAN_API_KEY}` and no literal credential. A live image is described and a voice sample is transcribed through Hermes or its explicitly identified provider/API path.
- [x] **AC3. Image use is bounded and selectable.** `flux-2-klein` and `qwen-image-2.1` are both declared, the active default is flux, and tests prove one shared counter across both models, UTC-month reset, fail-closed corruption handling, and refusal at 50 requests without calling the backend. One live image request proves the provider and records its remaining local budget.
- [x] **AC4. Memory writes and writable state recover.** The terminal renders `docker_run_as_host_user: true`; memories are effectively UID/GID 10000 with mode 0755 and no sticky bit; the zone and writable caches exist; stale locks are removed and ignored. Live memory mutation advances the file mtime, gateway and sandbox writes have matching effective ownership, and vault status contains no memory locks.
- [x] **AC5. Delivery is reproducible.** Focused tests, the repo test suite and lint pass; two consecutive `agent_stack` provisions succeed with `changed=0` on the second. The runbook documents the catalog, quota, ownership and verification boundaries, and the PR records any unfinished sibling follow-ups.

## References

- Bitácora: kubelab#2214 (AI-016), kubelab#3485 (AI-031), kubelab#2211 (AI-015), kubelab#1933 (AI-009)
- Siblings: kubelab#2175 (AI-013), kubelab#2299 (AI-018), kubelab#2189 (VPN-ACL-012)
- ADR: `docs/adr/adr-068-ace2-operator-agent-tooling.md`, especially D2, D4, D5 and D7
- Incident: `knowledge/80_agents/hermes-kubelab/sessions/2026-11-07-selfdiagnosis.md` (F1, F2, F5, F6)
- Upstream: `nousresearch/hermes-agent` v0.22.1 commit `297552a9d646119871391d202509822cd86330df`; v0.23.0/v0.23.1 release notes
- NaN: live `/v1/models` and completion/embedding/rerank probes, 2026-11-13; NaN model documentation for the shared 100-request image quota
