---
id: "APP-CONFIG-013-vikunja-shared-projects"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-10-15"
issue: "mlorentedev/kubelab#1701"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Production defect in daily use: tasks created by Slack and forge events are invisible to the human accounts (#1701 owner requirement of 2026-10-04); owner approved the override on 2026-10-16. (16 active, limit 10, 2026-10-15)"
---

# APP-CONFIG-013: Vikunja projects are declared, reconciled, and shared with every human

Superseded 2026-10-22 by CONSOLE-005 (#2587), which retires Vikunja; archived with AC7 and AC9 unmet for that reason.

## Why

<!-- from issue #1701: APP-CONFIG-013: sync-vikunja passes no token and reconciles a removed endpoint, so no project has ever been created -->

Tasks created by Slack `/task` and by forge events are invisible to the people they are for. Measured on prod (2026-10-16, read-only, with the n8n token): the token belongs to `operator` (id 1), the project `Bitacora` (id 2) is owned by `operator` and shared with nobody, and its 7 tasks were all created by `operator`. A user logging in as `manu` (id 2) sees an empty Vikunja, because Vikunja shows a project only to its owner and to whoever it is shared with. The owner requirement (#1701, 2026-10-04) is that the creating account must not decide visibility; today, with the company-wide model the owner wants for now, every human account sees every project, and access is narrowed later.

The reconciler that should have made this true has never run: `make sync-vikunja` passes no credential and its first call targets `/namespaces`, which Vikunja 1.0 removed (404). The `Bitacora` project exists only because someone created it by hand.

## What

- `make sync-vikunja ENV=<env>` authenticates from SOPS, with no flag and no exported variable, and reconciles three declared things idempotently:
  1. the **projects** (declared in `common.yaml`; today exactly `Bitacora`, the single board of ADR-066's revision), adopting an existing project by title instead of duplicating it;
  2. a **team** `kubelab` whose members are the human identities in `apps.auth.identities` (`superadmin`, `operator`; never `machine` or `reviewer`);
  3. a **share** of every declared project with that team, at the declared right.
- Narrowing access later is a change to the team's membership or to which team a project is shared with, not an edit of N projects × M users.
- The reconciler no longer registers a webhook as a side effect (see Out of scope).
- The reconciler uses its own token, `kind=EXTERNAL`, minted by `operator` in the browser; n8n keeps its minimal one.

## Out of scope

- The `agent-dispatcher` webhook registration. The workflow requires `headerAuth` and Vikunja can only sign with HMAC, so a registered hook would answer 403 on every event. Gated off here; a ticket carries the fix.
- **The formal task lifecycle** (states and deterministic transitions: issue opened → Todo, PR opened → In Review, PR merged → Done; the same states for every product). Owner decision 2026-10-16: split into a second spec, which absorbs #1687, #1684 and the transition half of #503. This spec only makes the board and its access declared and visible; the board stays single (ADR-066 revised), with the product carried by `area:*` labels, and independence between products and users comes from those labels and from the team, not from separate projects.
- Declaring the `area:*` labels in `common.yaml` (the reconciler keeps its current `DEFAULT_LABELS`); belongs to the lifecycle spec.
- #2312 (a failed Slack create ends silently). Separate lane, separate PR.
- Per-project permissions, OIDC team sync from Authelia groups, moving or re-owning existing tasks.

## Risks / open questions

- **Who mints the reconciler token (BLOCKER for the live run).** `GET /projects` returns only what the token's owner sees, and sharing a project needs admin on it. `Bitacora` is `operator`'s, so the token must be minted in an `operator` session. A token minted by `manu` would not see `Bitacora`, would create a duplicate and could not share the original.
- **Team routes may not be assignable to an API token.** Tokens are scoped per route group, and `GET /routes` (the listing) refuses API tokens (401, measured), so it cannot be read by API. The swagger document does list `/teams`, `/teams/{id}/members` and `/projects/{id}/teams`. Confirmed by consequence after minting (`GET /teams`); if it fails, fall back to sharing with users (`PUT /projects/{id}/users`) and amend this spec.
- **Verifying "as `manu`".** The owner's AC is a read as the human, not as the token's owner. `manu` signs in by SSO and has no password, so a token must be minted in their own session (read-only), or the last check is done in the browser by them. Decided at `verification.md`.
- **The token will outlive the Vikunja version it is minted on.** The upgrade to 2.7.0 (separate ticket) follows this rollout, and since 2.3.0 a token holding only a parent group (e.g. `projects.read_all`) no longer authorizes nested routes. When minting, select every group explicitly (`projects`, `projects_teams`, `teams`, `labels`) rather than relying on the parent, or the upgrade will look like a regression of this work.
- **SOPS key name (confirmed by the owner, 2026-10-16):** `apps.services.core.vikunja.reconciler_api_token`, next to `db_password` and `jwt_secret` (Vikunja's home), not under `automation`, which is n8n's namespace.
- **Members must already exist.** Vikunja creates accounts on first SSO login; both `operator` and `manu` exist today (`make vikunja-audit-users ENV=prod`). The reconciler fails closed, naming the missing user, rather than skipping it.
- **The existing `Bitacora` is matched by title, case-insensitively,** the way the workflow resolves it (`apps.services.core.vikunja.default_project`); a second project with that title would split the board.
- **Correction to the ticket:** the owner comment names the machine account `hefesto`. It does not exist in Vikunja (only `operator` and `manu`); the tasks' `created_by` is `operator`.

## Acceptance criteria

- [ ] **AC1** `make sync-vikunja ENV=<env>` authenticates from SOPS without the caller exporting anything, the token never reaches argv or stdout, and a missing token fails closed with a message naming the key.
- [ ] **AC2** After a run, `GET /projects` contains every declared project, an existing `Bitacora` is adopted rather than duplicated, and no call targets `/namespaces`. Read back, not inferred from the exit code.
- [ ] **AC3** The team `kubelab` exists, its members are exactly the declared human identities, and every declared project is shared with it at the declared right. Read back from `/teams/{id}` and `/projects/{id}/teams`.
- [ ] **AC4** A second run reports `changed=0`, exercised against a real server (staging first).
- [ ] **AC5** No test asserts an endpoint exists solely because a fake answers it: the client's request paths are checked against the paths in Vikunja's own swagger document (a recorded fixture), so a removed endpoint fails the suite.
- [ ] **AC6** The declared project set, the team name/right and the member identities live in `common.yaml`; a test fails if `default_project` is not a declared project, or if a member is not an identity, or is the `machine` or `reviewer` one.
- [ ] **AC7** Logged in as `manu` (token or browser), `Bitacora` and its tasks are visible in prod. Recorded in `verification.md` with how it was observed.
- [ ] **AC8** The reconciler registers no webhook, a test pins that, and a ticket exists for the signature mismatch with `agent-dispatcher`.
- [ ] **AC9** The reconciler's token is a `SecretSpec` with `kind=EXTERNAL`, `envs=("staging", "prod")` (never `"common"`), the `tk_[0-9a-f]{40}` `value_pattern`, and an honest `expiry`: never `Expiry.NEVER`, since Vikunja tokens expire. Expiry is asked from the issuer, never recorded (`secret_expiry.py`), so the value is `PROVIDER` if Vikunja's API can report a token's expiry to a checker, else `UNKNOWN` with a ticket. The same correction applies to the existing `n8n.vikunja_api_token` spec, which declares `NEVER` and expires 2026-12-04.

## References

- Bitácora board: mlorentedev/kubelab#1701 (owner requirement of 2026-10-04); related #1699, #1684, #2312
- Related ADR: ADR-066 (one board, revised 2026-09-05)
- Lessons: lesson-413 (a credential can exist and have no power), lesson-440 (a mock of an unmeasured boundary certifies the belief)
