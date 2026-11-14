---
spec: "AI-016-hermes-nan-capabilities"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "17126290b8590d53dfb6cc3162b22038c37f351d"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-14"
---

## Adversarial review

**Scope**: `AI-016-hermes-nan-capabilities` — whole change `git diff 167cb3aeba84eca3c1b87fa85ca5ec7455365ae8...HEAD`
(single branch commit `17126290 feat: restore Hermes NaN capabilities and memory writes`, no merges in range).
25 files, +1095/−74.
**Sources**: `specs/AI-016-hermes-nan-capabilities/{proposal,tasks,verification}.md`, `features.json`,
`review-request.json`; diff of `infra/config/values/common.yaml`,
`infra/ansible/roles/agent_stack/{defaults/main.yml,tasks/hermes.yml,tasks/vault_zone.yml,templates/*}`,
`infra/ansible/roles/agent_stack/files/hermes-plugins/nan/`, `infra/ansible/playbooks/provision-ace2.yml`,
`docs/runbooks/hermes-kubelab.md`, `tests/test_hermes_*`, `tests/test_open_webui_*`.

**Contract state**: `dotf spec digest AI-016-hermes-nan-capabilities` reproduces `review-request.json`
`contract_digests` byte-for-byte (`features.json`, `proposal.md`, `tasks.md`; `spec.md` empty — full spec, no
fast-track). No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain in the spec folder.

**Commands run in this session** (fresh, in this worktree; `poetry install --with dev` first):

| Command | Result |
|---|---|
| `poetry run pytest -q tests/test_hermes_nan_image_provider.py tests/test_hermes_config.py tests/test_open_webui_models.py tests/test_open_webui_rag.py tests/test_agent_stack_role.py tests/test_hermes_memory_permissions.py` | **130 passed** |
| Mutation, quota cap removed (`if state["used"] >= self.limit` deleted) | **3 failed** — `test_the_shared_counter_refuses_the_next_request_without_calling_nan`, `test_flux_and_qwen_draw_from_the_same_counter`, `test_parallel_calls_cannot_cross_the_cap` → cap tests are non-vacuous (red-green verified, reverted) |
| Mutation, corrupt state fails **open** (`_read` returns `used: 0` instead of raising) | **1 failed** — `test_corrupt_state_fails_closed_without_calling_nan` → fail-closed is genuinely guarded (reverted) |
| `poetry run pytest -q tests/test_hermes_digest.py tests/test_hermes_curator_judge.py tests/test_hermes_sidecar.py` (the three modified suites) | **76 passed** |
| `poetry run ruff check` on the new provider + new tests | All checks passed |
| Render probe: `hermes-config.yaml.j2` with `agent_config.plugins = {enabled: [custom/backend, image_gen/nan], some_key: {...}, disabled: [x/y]}` loaded through the strict duplicate-key loader | merge is correct — `enabled: [image_gen/nan, custom/backend]` (deduped, role entry first), `some_key` and `disabled` preserved, no duplicate key, all five new role sections present. Scratch script in `mktemp -d`, not committed. |
| `make lint` | `All checks passed!`, 168 files already formatted (exit 0) |
| `make lint-ansible` | `[SUCCESS] All 26 playbooks parse` (exit 0) |
| `git status --porcelain` after every probe | only `specs/AI-016.../review.md` + `review-request.json` (untracked) — probes reverted, tree clean |

Not run (out of reach from this worktree, marked UNVERIFIED): `make test` (10,457-test full suite) and any
`make provision NODE=ace2` idempotence run. The `changed=2 → changed=0` claim in `verification.md` is taken
as reported, not reproduced.

### Spec and task alignment

- **AC1 — one measured catalog.** `apps.services.ai.nan.models` is introduced in `common.yaml` and is the only
  source: `webui.env.j2` and `hermes-config.yaml.j2` both read `agent_stack_nan_models` (rendered from the
  SSOT through `provision-ace2.yml`), and `apps.services.ai.open_webui.models` + `rag.embedding_model` /
  `rag.reranking_model` are deleted. `grep -rn "webui\.models\|open_webui\.models"` over the tracked tree
  returns **nothing** — no orphan consumer. Chat list is the 11 measured models; `minimax-h3` explicitly
  asserted absent. `agent_stack` is included by exactly one playbook (`provision-ace2.yml:295`), so the new
  required role var has no second, un-provisioned entry point.
- **AC2 — pinned v0.22.1 capability keys.** Rendered config has `auxiliary.vision` (`qwen3.6`), `stt.openai`
  (`whisper`, `language: ""`), `tts.openai` (`kokoro`/`ef_dora`), `image_gen.openai`, each with the NaN base
  URL and `${NAN_API_KEY}`; no literal credential (`nan-key-sentinel` asserted absent from the dumped config).
  Live proofs are adapter-level, not Slack round trips — `verification.md` says so explicitly rather than
  overclaiming.
- **AC3 — bounded, selectable image use.** `image_gen.provider: nan`, `max_parallel_requests: 1`, both models
  declared with flux as `default_model_id`, quota 50 of NaN's 100 shared. Cap, cross-model sharing, month
  reset, corruption and parallel-crossing are each covered by a named test and all four survive mutation
  probes. `plugins.enabled` merge preserves any ported entries (`unique | list`), and `plugins` was added to
  `role_sections` so the ported-block loop cannot emit a duplicate YAML key.
- **AC4 — memory/ownership repair.** `docker_run_as_host_user: true`, host owner derived as
  `subid_start + 10000 − 1`, memories/proposals/zone `0755` with no sticky bit, cache/delegation/documents/
  workspace created deterministically, clone root `0700 → 0711` for traverse-without-list, stale `*.lock`
  removal ordered after both writer stops, namespace-aware sync preserved. `vault_zone.yml` is imported
  **before** `hermes.yml` in `tasks/main.yml`, so the repair's `compose stop` cannot leave the gateway down
  for the rest of the run.
- **AC5 — reproducible delivery.** `docs/runbooks/hermes-kubelab.md` records catalog, quota, ownership,
  traverse-only root, the deepseek-v4-flash vision false-negative and the sibling follow-ups (#3517).
  `verification.md` names every command and states its own boundaries (`make lint-ansible` is syntax parsing,
  not full `ansible-lint`; `dotf spec check` is not a subcommand).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | correctness / quota integrity | AC3 promises "at most 50 requests per UTC month". The counter is a single JSON file in `$HERMES_HOME/cache`; **absence is silently treated as `used: 0`** (`MonthlyImageQuota._read` returns a fresh state when `not self.path.exists()`). Corruption fails closed, but a *deleted* or never-restored file — cache wipe, `compose down -v`, a rebooted host path, or an operator unblocking a stuck agent by removing the file — resets the reserve to zero with no record, no log and no refusal. The 50 reserved for Open WebUI is then silently spendable, which is exactly the outcome the provider exists to prevent. Concrete path argued from code; not observed on ace2 (the file demonstrably survived gateway recreations). | `infra/ansible/roles/agent_stack/files/hermes-plugins/nan/__init__.py:63-65`; surviving-recreation evidence in `verification.md` AC3 | UNTESTED (no test for "state file disappeared mid-month") | code + tests: persist `used` across a missing file (e.g. anchor the month in a second file, or refuse a first claim late in a month without an explicit `--reset`), and add a named regression test |
| Minor | THEORETICAL | tests / upstream seam | The provider is tested against **stubs of the three upstream contracts it cannot live without**: `plugins.image_gen._common.load_image_gen_config`, `agent.image_gen_provider.error_response` and the inherited `OpenAIImageGenProvider.generate`. A signature or payload change on the pinned v0.22.1 side breaks `generate()` at runtime with every unit test still green. Partially mitigated: the new provision task reads `get_provider('nan').is_available()` back through the **live** registry each run, and one live flux image succeeded — so the seams are proven to have worked at least once, on the deployed image. | `tests/test_hermes_nan_image_provider.py:43-67` (fixture); `infra/ansible/roles/agent_stack/tasks/hermes.yml` "Read the NaN image provider through the live registry" | `test_the_quota_guarded_nan_provider_is_enabled_and_mounted_read_only`, `test_every_provision_reads_the_nan_provider_through_the_live_registry` (both assert config/task shape only, not the seam) | tests (add a contract assertion on the pinned image's real signatures, or a provision-step `generate()` dry-run guarded by `--check`) |
| Major | THEORETICAL | security / ownership blast radius | `Reclaim existing vault-zone ownership` chowns **every non-`curator` object in the whole zone** to the uid the change documents as *the sandbox's* write identity (container 10000 = host 534287) — not just `memories/` and `proposals/`, which is all the proposal names. Two consequences: (a) **write privilege widens inside the zone**: directories previously `0755` owned by the agent user become `0755` owned by that identity, which `verification.md` proves writes as `10000:10000` from a real `DockerEnvironment` — so the (untrusted-shell) side gains owner-write over zone files it previously could only read (session records, zone docs), while `curator/` is carved out precisely because a host-side owner needs to keep it; (b) unlike the stop/cleanup tasks it carries **no `_agent_stack_vault_repair_needed` guard and no "writers stopped" precondition**, so it runs on every provision while writers may be live, and any host-owned file that later reappears outside `curator/` is silently reconverted. Also O(all zone objects) task iterations per run. Not observed as breakage (clean second run reported `changed=0`), and git audit still surfaces what the sandbox writes — hence THEORETICAL, not REAL. The proposal's AC4 states only that *memories* gain effective UID/GID 10000, so the wider scope is unstated. | `vault_zone.yml` "Reclaim existing vault-zone ownership" (two `when` items, no repair guard) and `_agent_stack_vault_gateway_objects` rejecting only `.../curator(/|$)`; sandbox write identity `10000:10000 / 534287:534287` in `verification.md` AC4 | `test_existing_zone_files_are_reclaimed_without_touching_curator_inputs` asserts the task exists and honours the curator carve-out only — the blast radius and missing guard are UNTESTED | code + spec: either restrict the reclaim to `memories/` + `proposals/` (matching AC4) or state the zone-wide grant in `proposal.md` next round; add the repair-guard test |
| Minor | THEORETICAL | reliability | `Stop sandboxes before repairing shared vault files` uses `docker ps -aq --filter label=hermes-agent=1`, so it also destroys **stopped** (persisted) sandbox containers, not just running ones — their workspace is lost on any drift-triggered repair. Gated on `_agent_stack_vault_repair_needed`, so it is rare, and sandboxes are declared ephemeral, but the blast radius is wider than "stop the writers". | `vault_zone.yml`, `docker ps -aq … docker rm -f $ids` | `test_stale_locks_are_removed_only_after_writers_stop` (ordering only) — the `-a` scope is UNTESTED | code |
| Minor | THEORETICAL | correctness | The host owner is derived as `agent_stack_agent_subid_start + 9999` with no check that the subordinate range actually covers 10000 ids. If `agent_stack_agent_subid_count` were reduced below the in-container uid, the computed owner would fall outside the range and every memory write would fail closed on `EPERM` — with a misleading "ownership repair succeeded". | `defaults/main.yml` `_agent_stack_hermes_host_uid`/`_gid` | `test_host_ownership_is_derived_from_the_rootless_subordinate_ranges` asserts the arithmetic only | code (`assert`/`fail` when `subid_count < 10000`) + tests |
| Minor | THEORETICAL | scope | `proposals/` moves `01777 → 0755` owned by container uid 10000 (host subuid 534287 — the identity `verification.md` shows writing from a real `DockerEnvironment`). The container-side emitter is correct, but a host-side dispose path (an agent writing `status: disposed` into a draft on ace2 as the agent user) loses its write permission; the runbook text was updated for the sync but not for disposal. Mitigated if disposal always happens in the operator's own vault clone rather than the ace2 mirror. | `vault_zone.yml` proposals task; runbook "Curator judge and proposals" | `test_the_proposals_directory_is_the_kind_the_gateways_user_can_write_and_the_sync_can_read` (container direction only) | spec/runbook (state where disposal writes) — no code change if the clone is never the disposal target |
| Minor | SPECULATIVE | quality | `find file_type: any` + per-item `file:` chown follows symlinks, so a symlinked object inside the zone would have its **target** chowned, potentially outside the zone. No symlinks exist in the zone today. | `vault_zone.yml` "Read vault-zone ownership before repairing it" | UNTESTED | code (add `follow: false`) |
| Minor | THEORETICAL | SSOT / maintainability | Adding `auxiliary`, `stt`, `tts`, `image_gen` to `role_sections` means the template now **silently discards** those sections if an operator ever sets them in `hermes_kubelab.agent_config` in `common.yaml` — the ported-block loop (`for section, value in ported.items() if section not in role_sections`) never renders them, and nothing fails or warns. `plugins` escaped this because it is merged explicitly, and `model`/`delegation` are merged key-by-key too, so the new sections are the inconsistent ones. Empty today (verified: `agent_config` has none of the five), so this is a latent trap against the repo's own "SSOT for config" rule. | `hermes-config.yaml.j2:13` vs `:182-184`; `common.yaml` `hermes_kubelab.agent_config` key list | UNTESTED (no test renders a ported `stt`/`tts`/`image_gen`/`auxiliary` block) | code + tests: merge role-owned sections from `ported` the way `plugins` does, or assert at render time that they are absent |
| Question | — | process | `tasks.md` Closing section is still all `[ ]` (criteria coverage, PR opened, `dotf pr triage-queue`, handoff). Implementation batches are honestly ticked with matching evidence, but the closing gate — including "no unproven idempotency claim" — is unverified from inside this worktree. Confirm the PR exists and its triage is dispositioned before archive. | `tasks.md` Closing block | — | spec (verification.md disposition), not the contract set after this verdict |
| Question | — | ADR-068 D7 wording | The same `common.yaml` hunk rewrites the ADR-068 D7 comment to say scheduled/delegated work uses the "lower-cost legacy `unmetered` role" because "NaN now meters all chat models from one credit pool". That contradicts the ADR as cited by the runbook's premise (unmetered routes spend no credits). Comment-only, routing unchanged — but it is a factual claim about the ADR inside the config SSOT, carried in an unrelated spec's diff. | `common.yaml` models comment hunk | — | code (comment) or a follow-up ADR amendment — confirm the ADR text agrees |

No findings against the credential boundary: no literal secret appears in the rendered config, the provider
source, or the new tests (`nan-key-sentinel` asserted absent; `print(` asserted absent from the plugin source).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every AC has a named test and the quota/ownership logic survives mutation probes; the counter-loss path and the unstated zone-wide write grant are uncovered negative cases. |
| Verification       | A | `verification.md` names each command and its observed output, states what it does *not* prove (adapter-level voice/vision, syntax-only ansible lint) and records the failed first attempts; focused suite reproduced green here (130 passed). |
| Scope              | B | Diff matches proposal with two documented side-changes (clone `0700→0711`, proposals sticky-bit drop) and one unrelated comment rewrite of ADR-068 D7. |
| Reliability        | B | Fail-closed + locked + atomic + idempotent by construction and by live `changed=0`; the reservation is lost silently if the counter file disappears, the reclaim runs without a repair guard, and the sandbox `rm -f` is broader than needed. |
| Maintainability    | A | 146-line plugin, single responsibility, `generate()` well under CC 10, WHY-comments on every non-obvious choice, ruff clean, no dead code. |
| Handoff-readiness  | B | Runbook fully updated, sibling follow-ups (#3517, #2175, #2299, #2189) written down, verification rich; closing checklist unticked and no new lesson (declared "no, with reason"). |

Aggregation: no D, no C → **PASS** on the rubric axis. Severity axis: no Blocker, no REAL Major; both Majors are THEORETICAL → **PASS WITH GAPS**.

### Verdict

**PASS WITH GAPS**

`dotf spec archive` is **advisable** in the current state, provided the two Questions above are answered
(PR exists and its checks/review are dispositioned; the ADR-068 D7 comment is confirmed or ticketed). The
contract set (`proposal.md`, `tasks.md`, `features.json`) is frozen by this verdict — the majors and minors
below are tracked, not fixed, and editing a contract file now would invalidate this review.

### Recommended next steps

For the implementer to disposition in `verification.md` or carry into a follow-up ticket — **not** contract
edits:

1. **Zone write blast radius (Major, tracked).** Decide whether the sandbox identity really needs owner-write
   over the whole zone; if not, restrict `Reclaim existing vault-zone ownership` to `memories/` +
   `proposals/`, gate it on `_agent_stack_vault_repair_needed` and the writer stops, and add the named test
   for both. If yes, say so in the next round's `proposal.md` — AC4 as written claims only memories.
2. **Quota integrity (Major, tracked).** Decide and record whether a missing `nan-image-quota.json` should
   refuse the first claim late in a month instead of resetting to zero; if kept as-is, write the accepted
   risk into the runbook ("a deleted counter silently restores the 50-request reserve") and ticket the
   regression test for the disappearance case.
3. **Sandbox `-a` scope (Minor).** Narrow the `docker ps -aq` cleanup to running containers unless persisted
   sandboxes are intentionally disposable.
4. **Subuid range precondition (Minor).** Fail the role when `agent_stack_agent_subid_count < 10000` rather
   than computing an owner outside the range.
5. **Proposals dispose path (Minor).** One runbook sentence naming where `/curator dispose` writes (operator
   clone vs ace2 mirror), so the `0755` change is not rediscovered as a permission failure.
6. **Ported-section merge (Minor).** Merge `auxiliary`/`stt`/`tts`/`image_gen` from `agent_config` the way
   `plugins` is merged, or fail loudly when one is set — silent discard contradicts the config SSOT.
7. **Upstream seam coverage (Minor).** Note in the runbook that image generation is guarded by the
   per-provision live-registry assertion plus one live request, not by the unit suite.
