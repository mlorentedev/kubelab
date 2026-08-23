---
tags: [spec, tasks]
created: "2026-08-14"
---

# Tasks - AUTH-004-identity-and-machine-access

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.

> **Read [ADR-062](../../docs/adr/adr-062-platform-identity-model.md) first.** This list implements it. The single-identity plan recorded on #1013 was reversed on 2026-08-14; anything written against "rename `manu` to `operator`" is stale, including the ordering constraint it implied.

## Setup

- [x] Branch created from origin/master: `docs/adr-platform-identity-model` (ADR + amended proposal + this list; implementation branches come later, one per part) ✓ 2026-08-14
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-14 — amended to the two-tier model, ACs rewritten (AC2 tiers, AC7 break-glass drill added)
- [ ] No open questions left in `proposal.md` "Risks / open questions" — four remained (R1, R2, R5, R6) and every one of them is settled by observing a live instance, never by reading documentation. Part 0 exists to close them. Do not write configuration against a guess. **2026-08-15: R2, R5 and R6 are settled with transcripts in `verification.md`. R1 is still open and stays open until the operator authorises it — it touches prod Authelia.**

## Implementation

### Part 0 — settle the open questions against live instances, before any config

Nothing here changes state. Each task turns a guess into a recorded fact, and every one of them can invalidate a task below it — which is why they come first rather than being discovered mid-implementation.

- [x] [P] **R2 — inventory what is attached to Gitea's existing `manu` user id.** OIDC linkage, registered SSH keys, existing access tokens, and anything owned. Record the output in `verification.md`. **This is the task that decides whether the two-tier model's central claim holds** — that `manu` survives in place, so no account is deleted and no ownership migrates. If something forces a recreate, the pre-first-push deadline from the original plan comes back and Part 1 must run before the operator's first push. Do this one first, not in parallel. ✓ 2026-08-15 — **the claim holds.** uid 1 = `manu`, admin, and its only attachment is one SSH key (`msi-workstation`); zero repos, zero tokens, zero org membership, so no recreate is forced and the deadline stays dissolved. Three things surfaced that the task did not anticipate: (a) the live admin is `manu` while `common.yaml:469` declares `operator` — #951's drift, measured; (b) its root cause on this delivery path is `provision-bee.yml:222`, `gitea_admin_user: "{{ gitea_secrets.basic_auth.user }}"`, the *same* basic-auth alias as `k8s_secrets.py:52`; (c) `manu` has **no OIDC linkage at all** (`login_type: 0`, `external_login_user` empty), so ADR-062's superadmin presupposes a linking step nobody has taken — which sharpens R1 into "does the first SSO login link to uid 1 or fork a second account".
- [x] [P] **R5 — does Gitea derive admin from a group claim?** Read the live binary's own help (`gitea admin auth update-oauth --help`), not the documentation, for an admin-group option. Decides whether `manu`'s superadmin bit is declarative (a claim mapping, reconcilable) or a provisioning step (an explicit `--admin` on the account). `toolkit/scripts/configure_oidc.py` already drives `update-oauth`, so whichever answer comes back has a home. ✓ 2026-08-15 — **declarative.** Gitea 1.25.5 exposes `--group-claim-name`, `--admin-group`, `--restricted-group` and `--group-team-map`; `--restricted-group` is a ready-made lever for the `operator` tier that ADR-062 D2 did not know existed. None of them is currently passed: the bootstrap requests the `groups` scope and then ignores the claim. **Correction to this task's own premise** — the answer's home is *not* `configure_oidc.py`, which still `kubectl exec`s into a Gitea pod that ADR-061 deleted; it is `roles/beelink_services/files/gitea-bootstrap.sh`.
- [x] [P] **R6 — what does MinIO do with the `groups` claim?** ADR-016 asserts it maps groups to policies; nothing in this repo configures that mapping. Establish the live behaviour before claiming a tier is enforced there. ✓ 2026-08-15 — **nothing.** The running container has no `MINIO_IDENTITY_OPENID_*` variable at all: root credentials only, no identity provider, so no claim reaches it. ADR-016's assertion is aspirational. AC2 therefore cannot be demonstrated on MinIO — recorded as a named gap per ADR-062 D5, not counted as passing.
- [x] [P] **R4 — how is login prohibited on a bot account?** ✓ 2026-08-23 — **not through the CLI; through `PATCH /api/v1/admin/users/{username}` with `prohibit_login: true`.** This task did not exist until today: R4 is named as a risk in `proposal.md` and Part 3 is written as "gated on R4, R5", but Part 0 never listed it, so nothing was going to settle it. `gitea admin user` has six subcommands (`create`, `list`, `change-password`, `delete`, `generate-access-token`, `must-change-password`) and none touches `prohibit_login`; `--restricted` is a visibility tier, not a login block, and must not be read as a substitute. The admin API does expose it, and the asymmetry decides the provisioning ORDER: `prohibit_login` is in `EditUserOption` and **not** in `CreateUserOption`, so it cannot be set at creation and the bot exists briefly in a loginable state — create, then PATCH with a superadmin token, then mint the scoped token. AC5 survives as "provisionable from Ansible", but Part 3's line below understates it: it needs a superadmin token to exist first. ADR-062 D1's other candidate (never declaring the bot in Authelia) stays available but is omission, not enforcement; the spec asked for enforced.
- [ ] [P] **R1 — which flag combination enables OIDC-only onboarding.** Belongs to Part 2 but is cheap to settle in the same pass: create a throwaway Authelia user, attempt an SSO login against Gitea, observe. Both candidate mechanisms are in `proposal.md`; the answer is which one actually admits a new user while self-service registration stays closed. **STILL OPEN, deliberately** — it touches **prod** Authelia, so it needs the operator's explicit go-ahead before running. R2 also raised its stakes: it must now also answer whether an SSO login as `manu` links to the existing uid 1 or forks a second account. **2026-08-23 — the go-ahead was given for the reversible half and R1a is settled in `verification.md`: with today's configuration the SSO flow completes and then parks at `/user/link_account`, so onboarding needs a human at a form and AC3 fails by measurement, not by inference. Prod needed no change — the e2e `testuser` already existed in prod Authelia, so nothing was created and nothing reverted. Two things remain, and neither is this task: the headline "which flag combination admits a new user" cannot be answered without changing a flag on the live instance (a separate authorisation, and the change belongs in `gitea-bootstrap.sh` per R5), and **R1b stays parked**.**
- [x] Record all four answers in `verification.md` under a `## Open questions, settled` heading, each with the command run and its output. A settled question with no transcript is an assertion. ✓ 2026-08-15 — three of four recorded with full transcripts; R1's slot is left explicitly open rather than filled with a prediction.

### Part 1 — identity resolves from a declared SSOT map

The core fix, and it stands alone: no live account is touched, so it is safe to ship before Parts 2 and 3 and before the open questions above are fully settled — with the one exception that R2 may add a migration task to it.

- [ ] [AC6] Add a test that fails when a service's admin identity resolves from anything other than `apps.auth.identities`. Assert on the generated Secret content, not on the source file, so the test survives a refactor of how the value is plumbed. **Demonstrate it red first** — it must fail against today's `BASIC_AUTH_USER` mapping.
- [ ] [AC1] Add `apps.auth.identities: {superadmin: manu, operator: operator}` to `common.yaml`. Keep `apps.auth.admin_username` present for one commit so nothing breaks mid-change; its removal is a later task in this part.
- [ ] [AC1] Point `grafana-admin`'s `admin-user` at the resolved superadmin instead of `BASIC_AUTH_USER` (`toolkit/features/k8s_secrets.py:52`). The SSOT value is plaintext config rather than a SOPS-sourced env var, so this likely belongs in `SecretMapping.literals` rather than `keys` — check which before writing.
- [ ] [AC1] Do the same for MinIO's root user and for Gitea's admin user. Note the two live in different places: MinIO's is a SOPS key consumed by `minio-secrets`, Gitea's is an Ansible variable rendered into the Beelink compose file by `roles/beelink_services`. One decision, two delivery paths — neither should keep resolving from the basic-auth alias.
- [ ] [AC1] Replace the `is_admin: true` indirection with an identity-key reference in the Authelia users list, in **both** generators that resolve it (`toolkit/features/generator_authelia.py:171-175` and `toolkit/features/k8s_secrets.py:248-260`). Two generators reading the same SSOT by two mechanisms is the drift SSOT-014b was written to stop; this is the chance to leave one.
- [ ] [AC1] Add the second human's argon2 hash key to SOPS and register it in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py:122-130`, whose comment already anticipates this rename). **Check `envs` against the ANSIBLE-033 failure mode**: a tuple that matches no real env makes the secret vanish from every audit silently.
- [ ] [AC1] Remove `apps.auth.admin_username` and confirm nothing still reads it. `credentials.py:298-301` reads it as a default — that consumer needs the map too.
- [ ] [AC1] Confirm the red test from the first task now passes, and that `make secrets-audit` reports no gap for either environment.
- [ ] [AC1] Deploy to staging and authenticate against each of the three services as the resolved superadmin — a live response per service, per the acceptance criterion. A config diff is not evidence.

### Part 2 — SSO onboarding (gated on R1)

- [ ] [AC3] [AC4] Configure Gitea per R1's settled answer, declaratively rather than by hand — the CLI-vs-web-process caching gotcha in CLAUDE.md applies, so a restart is part of the change, not an afterthought. **Route corrected by R5:** this goes in `roles/beelink_services/files/gitea-bootstrap.sh` (which already drives `update-oauth` idempotently over `docker exec`), **not** `toolkit/scripts/configure_oidc.py` — that script still `kubectl exec`s into a Gitea pod that ADR-061 removed. Adding `--group-claim-name groups --admin-group admins` (and `--restricted-group` for the `operator` tier) to the existing call is the whole change.
- [ ] [AC3] Declare a throwaway user in `apps.services.security.authelia.users`, deploy, log into Gitea through SSO, and confirm an account appears with no manual step in Gitea. Capture the transcript, then remove the user.
- [ ] [AC4] Attempt an unauthenticated registration against Gitea and confirm it is refused. Demonstrated, not read off `app.ini`.
- [ ] [AC2] Log in as `operator` and confirm it is **refused** an administrative action that `manu` can perform. Where the service does not consume the group claim, record it as a named gap with its issue (Grafana → #951) rather than passing over it — per ADR-062 D5, an unenforced tier is the failure this model exists to prevent.

### Part 3 — machine identity (gated on R4, R5)

- [ ] [AC5] Provision a bot account from Ansible: account created, login prohibited per R4's settled mechanism, scoped token minted by `gitea admin user generate-access-token`, token written to SOPS and registered in `SECRET_CATALOG`.
- [ ] [AC5] Prove both halves of the scope: the token performs an operation its scopes allow, **and is refused** one they do not. Capture both responses. A token that works proves only half the claim.
- [ ] [AC5] Confirm the bot cannot authenticate through Authelia.

### Part 4 — break-glass and prod

- [ ] [AC7] Exercise the break-glass path once: a local-password login to one service while OIDC is unavailable, per ADR-062 D4. Document it in a runbook as exceptional. A break-glass path that has never been used is a hypothesis.
- [ ] [AC1] After merge, apply to prod and repeat the live authentication evidence there. Gitea's identity environment is prod (`gitea_identity_env`), so its check is not a staging one.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] `make test` green, and `make test-infra ENV=staging` shows no new failures
- [ ] Any gotcha that outlived the change is in CLAUDE.md or `docs/lessons.md`
- [ ] Board ticket #1013 reflects reality
