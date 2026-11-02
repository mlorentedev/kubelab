---
spec: "AI-025"
verdict: "FAIL"
reviewed_sha: "690bd91ca5bdb3a358873030f74dbaaeaf0fa133"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-01"
---

## Adversarial review

**Scope**: AI-025 — web search (SearXNG), default tools, memory review on ace2 (issue mlorentedev/kubelab#2915)
**Sources**: `specs/AI-025/{proposal,tasks,verification,features}.md|json`, `infra/ansible/roles/agent_stack/{defaults,main.yml,templates/*}`,
`infra/config/values/common.yaml`, `tests/test_open_webui_{web_search,code_and_memory,models}.py`, `tests/test_agent_stack_role.py`,
`tests/test_image_pull_budget.py`, `docs/lessons/containers-docker/lesson-{687,690,692}-*.md`.
Diff scope: `git diff 98b67498...HEAD` (113 files, +2423/−251). Contract digests from `dotf spec digest AI-025` match
`review-request.json` exactly (features.json `b8fd4f55…`, proposal.md `6abbe38e…`, tasks.md `b8e92940…`) — the contract is fresh.

**Note on diff composition.** Only the first-parent chain is AI-025's own work (`d7973c62`, `362e6d5e`, `50fb2e5f`, `344ad4ed`,
`31eb5210`, `ddfbbe69`, `bee62a06`, `c0e063d4`, `536392c5`, `a0191f60`, `690bd91c`). The rest of the 113-file diff arrived by
merging `origin/master` (secrets/ACME, offsite backups, netplan, Renovate, forge credentials, `specs/archive/GITOPS-003`) and is
not part of this change; I did not review it as AI-025's work.

**What I ran** (fresh, this session): `poetry run pytest -q --no-cov tests/test_open_webui_web_search.py
tests/test_open_webui_code_and_memory.py tests/test_open_webui_models.py tests/test_agent_stack_role.py
tests/test_image_pull_budget.py` → **83 passed**; plus `tests/test_renovate_image_coverage.py
tests/test_public_resolvers_ssot.py tests/test_ansible_config_keys_resolve.py tests/test_spec_verifications_select_tests.py`
→ **38 passed**. Every `features.json` command was run and its test count matches `verification.md` (6, 2, 1, 3, 74).

### Spec and task alignment

- All `tasks.md` boxes are ticked and every tick has diff evidence (SearXNG service/settings/env/role tasks, `defaultFeatureIds`,
  memory env, tests). No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain.
- `features.json` carries one entry per AC except AC1 ("speed measured, no change" — correctly not a feature), and each
  `verification` command is non-vacuous and passes. All five entries are still `state: pending` with empty `evidence`: the
  harness never captured the runs, so `verification.md`'s "every features.json command passes" is the author's claim, not the
  contract's. I confirmed the claim by hand (above); the empty states are a Minor, not a contradiction.
- AC wording is *replaced* by issue references: `proposal.md` §Acceptance criteria is a ticked list of paraphrases of
  #2915 AC1–AC6, so "done" for each AC is not decidable from the spec alone. That matters here — see Blocker 1, where the
  distinction between "memory carries a fact" and "a memory is written by background review" is exactly what AC4 needs.
- SearXNG hardening (proposal §Risks: "Whether the image starts that way is measured on ace2 before merge") is claimed met, but
  the numbers disagree across artifacts: `verification.md` AC2 says **95 MiB**, `lesson-690` says **128 MiB** measured locally.
  Minor, but it is the kind of discrepancy that makes a live claim unauditable.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker | THEORETICAL | memory mechanism | **AC4's mechanism cannot work on ace2 as written, and the evidence cannot tell.** `ENABLE_MEMORY_BACKGROUND_REVIEW` is wired into Open WebUI's `DEFAULT_CONFIG`, seeded into the SQLite `config` table on **first boot**, and afterwards the DB value wins over the env var (`Config.seed_defaults()` skips existing keys; `Config.get()` reads the row while `ENABLE_PERSISTENT_CONFIG` is the default true). ace2's instance booted long before this change (AI-009, then the v0.12.5 upgrade, #2885), so the key was seeded `false` with the env var absent — the `true` this change adds is very likely ignored. Either branch is a defect: (a) inert → AC4 is false and `proposal.md` ticks it; (b) enabled by hand in the Admin UI → the DB, not the repo, is the source of truth for AC4, and a rebuilt node loses it silently. | upstream open-webui#29091 (repro steps, root cause, closed as a *docs* fix 2026-08-28 — behavior unchanged); `infra/ansible/roles/agent_stack/templates/webui.env.j2:158-161`; `verification.md` AC4 cites only a template assertion plus "a fact told in one chat was recalled in a new chat" — which is also what an explicit memory-tool call does, and the proposal's own Why says memories were saved when asked | UNTESTED — `tests/test_open_webui_code_and_memory.py::test_memories_are_saved_without_being_asked` asserts the template's own strings, never the instance's effective config | code (role must write the value through the API/`configs/import`, not the env) + tests (a post-deploy assertion) + verification.md (record the deciding evidence) |
| Major | REAL (as a fact about the tests) / THEORETICAL (as a shipped failure) | verification design | **Four of the five ACs are "proved" by tests that assert the template against itself.** `test_memories_are_saved_without_being_asked`, `test_every_chat_starts_with_web_search_on`, `test_every_chat_starts_with_the_code_interpreter_on`, `test_every_chat_starts_with_the_image_tool_on` read `webui.env.j2` and compare it with `common.yaml`. They cannot fail because Open WebUI ignores, renames or persists-over a variable — which is exactly Blocker 1's failure mode, and it shipped green. Same shape for `test_open_webui_searches_through_searxng` (the name `SEARXNG_QUERY_URL`, `WEB_SEARCH_ENGINE` mapping is asserted, not exercised). | `tests/test_open_webui_web_search.py:78-85`, `tests/test_open_webui_code_and_memory.py:19-38`, `tests/test_open_webui_models.py:85-95`; all pass in a suite where nothing ever contacts Open WebUI | UNTESTED (no test observes an effective setting) | tests (one live assertion per AC on the node) + spec (say so in `verification.md`) |
| Major | THEORETICAL | reliability | **SearXNG has no post-deploy probe, unlike the sibling no-port service.** The role probes the MCP bridge from inside Open WebUI's container and asserts its status, refuses an unauthenticated call, and re-runs until it answers (`tasks/mcp_bridge.yml:8-30`); SearXNG gets none of that. If SearXNG crash-loops — a settings key Renovate's next image bump renames, or `cap_drop: ALL` meeting an image that now needs a capability — the play reports `changed=0` success while web search is silently dead. | `infra/ansible/roles/agent_stack/tasks/main.yml:360-366` (restart only, `changed_when: true`, no probe); no `searxng` probe anywhere in `tasks/`; `image: docker.io/searxng/searxng:2026.10.30-ffa88e3ba` is in `common.yaml` and `tests/test_renovate_image_coverage.py::*` passes, so Renovate *will* bump it unattended | UNTESTED — `tests/test_open_webui_web_search.py` checks the compose service's keys, not that it answers | code (`tasks/main.yml` + a `searxng-probe` stdin script) + tests |
| Minor | THEORETICAL | security | Web results are untrusted input, and background memory review turns them into persisted facts, so one poisoned result can survive the chat. Not in `proposal.md` §Risks, and no mitigation or acknowledgement. | `webui.env.j2` `ENABLE_WEB_SEARCH=true` + `ENABLE_MEMORY_BACKGROUND_REVIEW=true`, no prompt-injection note in proposal or lesson-690/692 | UNTESTED | spec (name the risk), vault (only if it generalizes) |
| Minor | REAL | tests | `test_memories_are_saved_without_being_asked` closes with `assert 1 <= review_interval_turns <= 10` — a magic bound with no stated reason, so it passes for any plausible value and documents nothing. | `tests/test_open_webui_code_and_memory.py:37` | n/a (the test is the finding) | tests |
| Minor | REAL | spec artifacts | `docs/lessons/containers-docker/lesson-687-*` was added in this change (image-tool toggle, the mechanism AC5 extends) and indexed, but `verification.md` §Promotion candidates lists only 690 and 692. | `git diff -- docs/lessons/containers-docker/_index.md`; `verification.md` §Promotion candidates | n/a | spec (`verification.md` — outside the contract set) |

**Questions for the author** (needs one command each on ace2, and they are what decide Blocker 1):

1. `curl -s -H "Authorization: Bearer <admin-token>" http://<tailscale>:3000/api/v1/configs/export` — what is
   `memories.background_review.enable` and `memories.review_interval_turns`? If `false`/`10`, the env vars are inert and AC4 is
   `verification.md`-level false.
2. `curl -s -H "Authorization: Bearer <admin-token>" http://<tailscale>:3000/api/v1/memories/` — is there any entry with
   `meta.created_by == "background_review"`? An explicit model tool call produces `created_by: user`, so this distinguishes the
   two paths that AC4 conflates.
3. Same export, for `code_execution_engine` / `code_interpreter.enable` and the model metadata defaults: is AC5's
   `defaultFeatureIds` read from the env at all, or from a persisted row?

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | AC2/AC6 hold; AC4's env mechanism is documented-inert on a booted instance and its live evidence cannot tell background review from an explicit memory call; AC5's default is asserted only at the template. |
| Verification       | C | Evidence is 83 green tests that compare templates to `common.yaml`, plus live claims (`95 MiB`, `33 results`, operator chats) that are neither reproducible nor consistent across artifacts (95 vs 128 MiB). |
| Scope              | B | AI-025's own commits are scoped to the role, `common.yaml` pin, tests, lessons and the spec; the other ~90 changed files arrived by merging `origin/master` and are documented above as out of this change. |
| Reliability        | C | SearXNG gets no post-deploy probe (the MCP bridge has four), so a dead search engine deploys as success; memory config has no rollback or drift check either. |
| Maintainability    | B | Env/template comments explain *why* (limiter needs Valkey, non-global fetch refused, Pyodide vs Jupyter); secrets are `0600`+`no_log`; one magic bound in a test. |
| Handoff-readiness  | B | `verification.md` filled, two lessons promoted and indexed, lessons cited; `features.json` left `pending` with empty `evidence`, and lesson-687 missing from the promotion list. |

### Verdict
FAIL

One Blocker: AC4 is archived as met on evidence that cannot distinguish "the env var took effect" from "the DB already had it",
and Open WebUI's documented persistence (`seed_defaults()` + `Config.get()`, upstream #29091) says the env value is ignored on an
instance that booted before it was set — which ace2 did. A Blocker stops the archive regardless of the reality tag, and the two
Cs in the rubric put the floor at PASS WITH GAPS on their own. The two Majors (template-only tests, missing SearXNG probe) are
tracked and would not by themselves have blocked.
`dotf spec archive AI-025` is **not** advisable in this state.

### Recommended next steps

**Minimum to flip to PASS** (all outside the contract set, so no re-review of the contract is triggered by them):
1. Run question 1 above on ace2 and paste the two values into `verification.md` §Evidence under AC4. If
   `memories.background_review.enable: true`, the Blocker is closed as a false alarm — record the output and re-review.
2. If it is `false` (likely): write the value through the API from the role instead of relying on the env (`POST
   /api/v1/configs/import` with `memories.background_review.enable` / `memories.review_interval_turns`, keyed off
   `common.yaml`), and record the same export as evidence. That is code + tests; the contract set stays untouched only if
   AC6's "the role's env and templates hold all of it" is read as "the role puts it in place", which I would accept in
   `verification.md`. If instead the AC is to be *narrowed* (env-only, DB drift accepted), that is a `proposal.md` edit —
   fix, then re-review, per the contract-set rule.
3. Add a named test that fails today: a `mcp_bridge.yml`-style probe (`docker exec open-webui` → `GET
   http://searxng:8080/search?q=test&format=json`, assert 200 and one result) with `until`/`retries`, and, in the suite,
   the assertion that every service the role brings up has one. Fixes Major 3 and gives AC2 a test that is not a template
   comparison.
4. Record in `verification.md` what the 95 MiB vs 128 MiB discrepancy actually is, and add lesson-687 to §Promotion candidates.
   Both are `verification.md` edits — excluded from the staleness check on purpose.

**Ticketed, not blocking** (file on the bitácora with the root cause above): the prompt-injection-into-memory risk, and the
`1 <= n <= 10` magic bound. Do not edit `proposal.md`/`tasks.md`/`features.json` to carry them — that invalidates this verdict
the moment it is written; `verification.md` is the place to disposition them, and it is the file the archive reads for them.
