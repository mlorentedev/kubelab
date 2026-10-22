---
tags: [spec, tasks, templates]
created: "2026-10-15"
---

# Tasks - APP-CONFIG-013-vikunja-shared-projects

> TDD order. One task = one focused commit. Tick as you go. Commit only when the owner asks.
> Run tests with `make test` / `poetry run pytest <file>`; never raw `kubectl`.
> Likely over the ~300 LOC cap: if so, split at the line between **PR A** (SSOT, client, reconciler, fixtures) and **PR B** (CLI, token, Makefile, rollout).

## Setup

- [x] Branch `fix/tasks-vikunja` already exists in this worktree; `make worktree-init` done
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-10-16
- [x] No open questions left in `proposal.md` that block code (the token and the `manu` verification are rollout-time, not code-time) ✓ 2026-10-16

## Implementation

### PR A: declaration, client, reconciler

- [x] [AC5] Record `tests/fixtures/vikunja/swagger-paths-1.0.0.json`: the `paths` (method list per path) from `https://tasks.kubelab.live/api/v1/docs.json`, read-only fetch, no secrets
- [x] [P] [AC5] Failing test in `tests/test_vikunja_api_contract.py`: every endpoint the client calls exists in the fixture with that method, and `/namespaces` is not called. Expected: FAIL (`get_namespaces` still calls it)
- [x] [AC6] Failing test `tests/test_vikunja_ssot.py`: reads `common.yaml` via `yaml.safe_load`; `default_project` is in `projects`; team members resolve to `apps.auth.identities` and exclude `machine` and `reviewer`. Expected: FAIL (keys absent)
- [x] [AC6] Declare `projects`, `team: {name, right}` and `team.members` (identity keys) under `apps.services.core.vikunja` in `infra/config/values/common.yaml`
- [x] [AC2][AC3] Client: remove `get_namespaces`/`create_namespace`; add `create_project`, `get_teams`, `create_team`, `get_team`, `add_team_member`, `get_project_teams`, `share_project_with_team`. Paginate list calls (`per_page`)
- [x] [AC2][AC3][AC4] Failing tests in `tests/test_vikunja_reconciler.py`: creates a missing project; adopts `bitacora` case-insensitively; creates the team; adds only missing members; shares only unshared projects; a missing user raises naming the username; second run `changed=0`
- [x] [AC2][AC3][AC4] Reconciler: `_reconcile_projects`, `_reconcile_team`, `_reconcile_shares`; `ReconcileResult` counts projects/team members/shares/labels
- [x] [AC8] Failing test then change: `reconcile()` registers no webhook (`create_webhook` never called); keep the method, remove the call
- [x] Refactor: delete `DEFAULT_NAMESPACES`; the declaration is read from the config, passed into `VikunjaReconciler`

### PR B: CLI, token, rollout

- [x] [AC1] Failing test in a new `tests/test_sync_vikunja_cli.py`: with no flag and no env var the token comes from SOPS key `apps.services.core.vikunja.reconciler_api_token`; never in `argv`; missing token exits non-zero naming the key
- [x] [AC1] `toolkit/cli/sync.py` `sync_vikunja_cmd`: the token comes from SOPS only (no `--token` flag, no environment variable: one source, nothing in argv), declared projects/team wired into the reconciler
- [x] [AC9] `SecretSpec` for `reconciler_api_token` (`kind=EXTERNAL`, `envs=("staging","prod")`, `value_pattern=tk_[0-9a-f]{40}`), and `n8n.vikunja_api_token` corrected from `Expiry.NEVER`. Neither `PROVIDER` (an API token is refused on `GET /tokens`, 401, measured 2026-10-18) nor `UNKNOWN` (`test_every_catalog_entry_is_now_classified` forbids it) fits, so a new class `Expiry.DECLARED`: the date the operator chose at mint is recorded per env in `secret_expiry.declared` of `values/<env>.yaml`, and an env with no date is a finding. Tests: `tests/test_vikunja_reconciler_token_spec.py` ✓ 2026-10-18
- [x] `Makefile`: update the `sync-vikunja` description (namespaces → projects, team, labels)
- [x] [AC8] File the ticket for the `agent-dispatcher` signature mismatch (HMAC vs `headerAuth`): #2326 (APP-CONFIG-019)

### Rollout (needs the owner)

- [x] Owner, in an `operator` session (staging done 2026-10-16; prod pending): mint the reconciler token selecting every group explicitly (`projects`, `projects_teams`, `teams`, `labels`: create/read/write; webhooks not needed); `toolkit secrets set ... --env staging|prod`
- [x] Read-only consequence check (staging: `/projects`, `/teams`, `/labels` all 200): `GET /teams` with the new token answers 200 (confirms the route group is assignable)
- [x] [AC2][AC3][AC4] `make sync-vikunja ENV=staging` (2026-10-16: 0 projects, 1 team, 1 member, 1 share, 8 labels; second run `changed=0`), read back projects/team/shares, re-run for `changed=0`
- [x] [AC2][AC3][AC4] Same on prod ✓ 2026-10-18 (Bitacora adopted, 1 team, 1 member, 1 share, 8 labels; second run `changed=0`; issue #1701 comment of 2026-10-18)
- [ ] [AC7] Verify as `manu` (read-only token from their session, or the browser); record how in `verification.md` — **not done; superseded by CONSOLE-005 #2587 (2026-10-22)**

## Closing

> Disposition 2026-10-22: archived as superseded by CONSOLE-005 (#2587), which retires Vikunja under the ADR-066 amendment (#2575, merged). The code and the prod rollout are done (#2324, #2331, #2464; prod `changed=0` on 2026-10-18). AC7 (verify as `manu` in prod) and AC9 (honest token-expiry class) stay unmet because both concern a service that is about to be deleted; neither is marked passing. Unticked boxes:
> - AC7 task (Rollout): not done, for that reason.
> - "Every acceptance criterion is covered by at least one test" and "matching entry in `features.json` with a non-vacuous verification command": AC7 has no test (it was an observation) and AC9 has tests but an unmet class; their entries are `blocked`/superseded with `verification: none: superseded`, so the boxes are not claimed.
> - Type checks and lint: not re-run, because this archive changes no code. The work PRs ran them in CI.
> - "No unrelated changes in the diff": a statement about a PR diff; the archive changes only this spec folder, and no single PR of this spec is claimed to close it.
> - "PR opened with `Closes #1701`": the work shipped as #2324, #2331 and #2464, none closing #1701, which is still open; the operator closes it with the archive, pointing at #2587.

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in; lesson written if the swagger-fixture technique proves out ✓ 2026-10-22 (lesson-578)
- [ ] PR opened with `Closes #1701`, `## Knowledge` section and `## Review triage` comment

## Machine-readable features

See `features.json`. The agent never writes `"state": "passing"`; the harness does after running `verification`.
