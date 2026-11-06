---
spec: "AUTH-022-agent-forge-identity"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "caeaabbf591cd909153ca234734d4e1be0266605"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-06"
---

## Adversarial review

**Scope**: AUTH-022-agent-forge-identity (`git diff b2e66648d2e2b5b986bbc0924a31614bbb0983ca...HEAD`)
**Sources**: `specs/AUTH-022-agent-forge-identity/{proposal,tasks,verification}.md`, `features.json`; diff over `toolkit/`, `infra/ansible/`, `infra/config/`, `docs/`, `tests/`

### Spec and task alignment

All five acceptance criteria are met, with verification evidence and reproducible tests:

- **AC1 (identity, scopes, catalog, rotation)** — independently verified. Running `.venv/bin/pytest --no-cov -q tests/test_gitea_agent_identity.py tests/test_gitea_token_scopes.py tests/test_gitea_token_rotation_registry.py` passes all 52 tests. The agent token `kubelab-agent` is pinned by equality to `write:issue,write:repository` (`AGENT_SCOPES`), registered in `ROTATABLE_TOKENS["agent"]`, recorded under `apps.services.core.gitea.agent_token` in `SECRET_CATALOG`, and wired through Ansible bootstrap and token minting/recording tasks.
- **AC2 (idempotent provisioning)** — Ansible tasks in `infra/ansible/roles/beelink_services/tasks/main.yml` mint the token via `gitea admin user generate-access-token --raw` and record via `toolkit secrets set --stdin`, gated on `when: gitea_agent_user | length > 0 and not gitea_agent_token`. The orphan revocation loop covers `kubelab-agent` on `dedalo` when SOPS is unpopulated. Verified by live measurement on 2026-11-06 on bee: `ok=53 changed=0 unreachable=0 failed=0` after removing the crashing runner container (#3149).
- **AC3 (reconciliation & collaborator write)** — independently verified. Running `.venv/bin/pytest --no-cov -q tests/test_gitea_agent_identity.py -k 'plan or collaborator or execute'` passes 7 targeted tests. `load_declaration` parses `writers: [agent]`, maps identity keys to usernames, and refuses invalid or administrative identities (`superadmin`, `reviewer`). `ensure_collaborator` issues `PUT .../collaborators/{login}` with `write` and immediately reads back both collaborator membership and effective permission via `is_collaborator` and `get_collaborator_permission` (handling lesson-707 where public repos floor at `read`). A converged grant is a no-op.
- **AC4 (token copy to Bitwarden)** — `make secrets-copy-gitea-agent-token` extracts the secret using `$(...)` into a shell variable, strictly checks `[0-9a-f]{40}` length/hex format via `grep -Eqx`, and pipes via builtin `printf %s` directly into `dotf secrets set --yes GITEA_KUBELAB_AGENT_TOKEN`. The value never reaches process argv or stdout. Verified by unit tests (`test_the_bitwarden_copy_never_puts_the_value_in_argv`, `test_the_bitwarden_copy_takes_a_gitea_token`, `test_the_bitwarden_copy_refuses_anything_but_a_gitea_token`).
- **AC5 (PR author attribution)** — verified live on `personal/imagesensortool#152` where `.user.login == dedalo`.
- **Mutation check**: mutated `AGENT_SCOPES` in `toolkit/features/gitea_tokens.py` to drop `write:repository`; `test_the_grant_is_exactly_issue_and_repository_write` turned **red** immediately with an assertion mismatch, and reverted cleanly.
- **Contract digests**: verified via `dotf spec digest AUTH-022-agent-forge-identity`; digests for `proposal.md`, `tasks.md`, and `features.json` match `review-request.json` exactly.
- **No unhandled drafts**: no `[AGENT-DRAFT]` or `[AGENT-SUGGESTION]` markers in the spec folder.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | auth / test guard | `tests/test_machine_identities_not_authelia_users.py` and `tests/infra/test_machine_identities_refused_live.py` (added in PR #3132 within the review scope) hardcode `MACHINE_IDENTITY_KEYS = ("machine", "reviewer")`, omitting `"agent"` (`dedalo`). While ADR-062 D1 establishes that all machine identities must have interactive login prohibited and be excluded from Authelia, the automated guard test suite added to enforce this boundary failed to incorporate the new third machine identity introduced by AUTH-022. If `dedalo` were accidentally declared in `apps.services.security.authelia.users`, CI would not catch it. | `tests/test_machine_identities_not_authelia_users.py:28`; `ConfigurationManager(env)` shows `agent: dedalo` declared in dev/staging/prod, but unchecked by this test suite. | UNTESTED (omitted from `MACHINE_IDENTITY_KEYS`) | tests |
| Minor | REAL | cli / maintainability | `toolkit services gitea rotate-token --help` displays `--token <str> Which credential: bot or admin [default: bot]`, omitting `agent` (and `reviewer`), even though `ROTATABLE_TOKENS["agent"]` is fully implemented and supported. | `.venv/bin/toolkit services gitea rotate-token --help` output; `toolkit/cli/services.py:896`. | UNTESTED (CLI help string not asserted in tests) | code |
| Minor | REAL | resilience / error reporting | `_report_machine_ownership` in `toolkit/cli/services.py` prints `[red]AUTH-022 AC3 VIOLATED[/red]` if the agent identity owns any repositories, but returns without raising an exception or setting a non-zero exit code. A rogue repository created by `dedalo` is reported visually but does not fail reconcile. | `toolkit/cli/services.py:443-449`. Tracked in follow-up issue #3148 (AUTH-024). | `test_reconcile_reports_what_the_agent_owns` in `tests/test_gitea_agent_identity.py` | code / follow-up ticket (#3148) |
| Minor | THEORETICAL | auth / scope boundaries | The `write:repository` token scope permits repository creation/forking under `dedalo`'s own account (since Gitea has no creation limit configured), and collaborator `write` allows direct pushes to default branch on `personal/imagesensortool` (no branch protection configured). | Analyzed and documented in ADR-062 amendment. Hardening tracked in follow-up issue #3148 (AUTH-024). | UNTESTED (Gitea instance settings) | vault / follow-up ticket (#3148) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All acceptance criteria AC1-AC5 verified; minor test guard gap on Authelia exclusion. |
| Verification       | A | Reproducible commands and live outputs recorded with timestamps; automated features verified via pytest. |
| Scope              | A | Diff cleanly matches the proposal; unblocker changes to disable crashing github-runner documented and justified. |
| Reliability        | A | Strong idempotency with orphan cleanup; read-back verification after collaborator PUT; secure subshell token copy. |
| Maintainability    | A | Modular structure, functions have CC <= 4, comments explain WHY, 409 lines of thorough tests. |
| Handoff-readiness  | A | ADR-062 amendment in place, lesson-707 and recovery runbook updated, follow-ups ticketed (#3148). |

### Verdict
PASS WITH GAPS

One open Major, and it is **THEORETICAL** (latent: `dedalo` is currently not listed in `authelia.users` in any environment, but the guard test omitted it from the checked set). Three Minors (two REAL, one THEORETICAL), all tracked. No Blockers, no REAL Major, and no rubric dimensions below B. Under the severity × reality rule, the change passes with gaps, and all gaps are tracked.

### Recommended next steps

Every item below is outside the contract set (`proposal.md`, `tasks.md`, `features.json`), which is closed by this verdict — do **not** edit those three; any edit invalidates this review and its archive permission.

- **Authelia guard coverage (Major)** — Add `"agent"` to `MACHINE_IDENTITY_KEYS` in `tests/test_machine_identities_not_authelia_users.py` and `tests/infra/test_machine_identities_refused_live.py`.
- **CLI help docstring (Minor)** — Update the `--token` help text in `toolkit/cli/services.py:896` to mention `agent` and `reviewer`.
- **Follow-up ticket #3148 (AUTH-024)** — Track and implement the open security exposures (fail on ownership violation, branch protection on `personal/imagesensortool`, limit repository creation on `dedalo`).
- **Disposition record** — Record these findings and dispositions in `verification.md` (applied, ticketed, or declined with a reason).
- **Archive** — `dotf spec archive AUTH-022-agent-forge-identity` is **advisable**: the review passes with gaps, all contract digests match `review-request.json`, promotion candidates are answered, and no `[AGENT-DRAFT]` tags remain.
