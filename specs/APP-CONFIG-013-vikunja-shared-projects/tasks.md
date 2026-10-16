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
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` that block code (the token and the `manu` verification are rollout-time, not code-time)

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

- [ ] [AC1] Failing test in a new `tests/test_sync_vikunja_cli.py`: with no flag and no env var the token comes from SOPS key `apps.services.core.vikunja.reconciler_api_token`; never in `argv`; missing token exits non-zero naming the key
- [ ] [AC1] `toolkit/cli/sync.py` `sync_vikunja_cmd`: resolve token (flag > env > SOPS), fix help text, wire the declared projects/team into the reconciler
- [ ] [AC9] `SecretSpec` in `toolkit/features/secrets_manager.py` (key path confirmed by the owner 2026-10-16): `kind=EXTERNAL`, `envs=("staging","prod")`, `value_pattern=tk_[0-9a-f]{40}`, `expiry=PROVIDER` or `UNKNOWN` (read `secret_expiry.py` first; Vikunja must be able to report a token's expiry for `PROVIDER`), `rotate_note` stating it is minted by `operator` with every group selected explicitly; correct `n8n.vikunja_api_token`'s `Expiry.NEVER`; assert it in a new `tests/test_vikunja_reconciler_token_spec.py`
- [ ] `Makefile`: update the `sync-vikunja` description (namespaces → projects, team, labels)
- [ ] [AC8] File the ticket for the `agent-dispatcher` signature mismatch (HMAC vs `headerAuth`); put its number in `verification.md`

### Rollout (needs the owner)

- [ ] Owner, in an `operator` session: mint the reconciler token selecting every group explicitly (`projects`, `projects_teams`, `teams`, `labels`: create/read/write; webhooks not needed); `toolkit secrets set ... --env staging|prod`
- [ ] Read-only consequence check: `GET /teams` with the new token answers 200 (confirms the route group is assignable)
- [ ] [AC2][AC3][AC4] `make sync-vikunja ENV=staging`, read back projects/team/shares, re-run for `changed=0`
- [ ] [AC2][AC3][AC4] Same on prod
- [ ] [AC7] Verify as `manu` (read-only token from their session, or the browser); record how in `verification.md`

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in; lesson written if the swagger-fixture technique proves out
- [ ] PR opened with `Closes #1701`, `## Knowledge` section and `## Review triage` comment

## Machine-readable features

See `features.json`. The agent never writes `"state": "passing"`; the harness does after running `verification`.
