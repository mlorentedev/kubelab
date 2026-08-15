---
id: "AUTH-004-identity-and-machine-access"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-14"
issue: "mlorentedev/kubelab#1013"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# AUTH-004-identity-and-machine-access

> **Amended 2026-08-14** after the single-identity decision was reversed in favour of a two-tier model. The architecture now lives in [ADR-062](../../docs/adr/adr-062-platform-identity-model.md); this spec implements it. What changed and why is recorded in ADR-062 D0 and on #1013.

## Why

<!-- from issue #1013: AUTH-004: MinIO and Gitea admin usernames still 'manu', aliased through a Traefik basic-auth secret -->

Three separate gaps share one cause: the platform has an identity provider and does not actually use it as the identity plane.

1. **Identity arrives by accident, not by declaration.** `k8s_secrets.py:52` maps Gitea, MinIO and Grafana's `ADMIN_USER` to `BASIC_AUTH_USER` — a Traefik basic-auth secret with no semantic relationship to application identity, whose value is the OS-level login `manu`. Meanwhile `common.yaml` declares `apps.auth.admin_username: operator` as the SSOT. The two never met: authenticating against `gitea.kubelab.live` as `operator` returns `401`; as `manu`, `200`. This is #1013, open since 2026-08-12. The defect is the **alias**, not the name — a service's admin should be readable off `common.yaml`, not traced through a basic-auth secret.

2. **There is no privilege boundary to place anyone in.** Authelia defines two groups (`admins`, `users`) and one human user who is in both. Argo CD is the only service that consumes them (`infra/helm/argocd/values.yaml:185`). So there is no lesser tier: every routine action runs with total power, and there is nowhere to put a second person or an agent.

3. **SSO cannot onboard anyone.** Read from the live `app.ini` on the Beelink: `[service] DISABLE_REGISTRATION = true`, and **no `[oauth2_client]` section at all**, so OIDC auto-registration sits at its default of off. A new collaborator would authenticate against Authelia successfully and then be refused by Gitea for having no account. Adding a person today therefore means creating a local account by hand — the non-reproducible path this project rejects everywhere else.

4. **No machine identity at all.** There is no pattern for giving an agent access to a repository. The only credential that exists is the human admin's password, so "let an agent work in Gitea" currently means handing it the operator's own account.

**On timing.** Gitea holds 0 repositories and 1 user right now (captured under `AC4-EVIDENCE` in the ADR028-004 spec). Under the two-tier model the `manu` account **survives** as the declared superadmin, so the deadline that drove the original single-identity plan — rename before the first push, because Gitea's CLI has no `rename` subcommand (verified against the live binary: `list`, `change-password`, `delete`, `generate-access-token`, `must-change-password`, and nothing else) — no longer applies to the common case. It still applies to any path that turns out to require recreating the account, which is what R2 exists to rule out. Verify before relying on it.

## What

Implements [ADR-062](../../docs/adr/adr-062-platform-identity-model.md).

- **Two human identities, at two privilege tiers.** `manu` is the named human superadmin (Authelia group `admins`); `operator` is the impersonal day-to-day account (`users`), with no administrative rights. Both are declared once in the identity map and referenced by key.
- **Identity resolves from a declared SSOT map.** `apps.auth.identities: {superadmin: manu, operator: operator}` in `common.yaml`. Gitea, MinIO and Grafana stop resolving their admin from `BASIC_AUTH_USER` and resolve it from a key of this map. The Authelia users list references identities by key too — an entry declares *which identity it is*, replacing today's `is_admin: true` + `admin_username` indirection with one mechanism instead of two.
- **SSO is the human login path.** OIDC auto-registration enabled so that declaring a user in `apps.services.security.authelia.users` (plus their argon2 hash in SOPS) is the whole of "add a person" — users as code. Self-service registration stays closed.
- **Break-glass is a second auth path on one account.** Each service's `manu` account holds a local password in SOPS *and* an OIDC link; the local password is documented as the path used when the IdP is unavailable and at no other time (ADR-062 D4). No separate `breakglass` accounts.
- **A machine-identity pattern.** A dedicated Gitea account per agent — never a shared human account, never `operator` — with a scoped access token minted reproducibly by `gitea admin user generate-access-token --username <bot> --token-name <n> --scopes <read|write>:<block>` from Ansible, the token registered in `SECRET_CATALOG`, and login prohibited on the account. Deploy keys for single-repository access, where a token would be wider than needed.

## Out of scope

- **Renaming the OS-level user.** `networking.ssh_users.homelab` is `manu` and stays `manu`. It is a different concept from the application identity — CLAUDE.md's SSOT-014 section already draws this distinction — and changing it is a per-node migration tracked separately as `SSH-RENAME-001`. Note that under the two-tier model the OS user and the superadmin identity now share a name *by decision* rather than by accident; they remain separate concepts.
- **Argo CD and Authelia's own admin accounts.** Both already resolve from the SSOT; this spec only covers the three services aliased through `BASIC_AUTH_USER`.
- **Retiring `BASIC_AUTH_USER` itself.** It also feeds the Traefik basic-auth middleware. Removing that consumer is a separate change; this spec only stops the three service admins from depending on it.
- **Grafana's group→role mapping.** Already tracked as #951. This spec cites it as the reason Grafana's tier is not enforced on day one; it does not absorb it.
- **Onboarding an actual second human.** This spec builds the path and proves it with a throwaway identity; using it is not a deliverable. The agent path *is* a deliverable (AC4).

## Risks / open questions

- **R1 — which flag combination actually enables OIDC-only onboarding.** Two candidates: `oauth2_client.ENABLE_AUTO_REGISTRATION=true`, or `DISABLE_REGISTRATION=false` together with `ALLOW_ONLY_EXTERNAL_REGISTRATION=true`. The docs describe both mechanisms without stating how they interact when registration is disabled globally. **Must be settled by testing against the live instance, not by reading** — create a throwaway Authelia user, attempt an SSO login, observe. Guessing here produces a config that looks right and silently refuses people.
- **R2 — does anything force recreating the `manu` account?** Under the two-tier model the account survives, so nothing *should*. Confirm before relying on it: inventory what is attached to its user id (OIDC linkage, registered SSH key, existing tokens) and confirm the account can be moved to the declared identity key without a delete. If something does force a recreate, the pre-first-push window from the original plan comes back and the ordering constraint returns with it.
- **R3 — Grafana and MinIO are not empty in the same way.** Gitea has no content. Grafana owns dashboards and MinIO owns buckets, both possibly attributed to the current admin. Check ownership before assuming a uniform approach, and treat them as separate tasks if it differs.
- **R4 — a bot account must not be able to log in through SSO.** Decided in principle by ADR-062 D1 (machine identities hold a scoped token and nothing else); what remains is which mechanism enforces it — `prohibit_login` on the Gitea account, never declaring it in Authelia, or both. Enforced, not conventional.
- **R5 — can Gitea derive admin from a group claim?** ADR-062 D2 puts `manu` in `admins` and expects the superadmin tier to follow from the claim. Whether `gitea admin auth add-oauth` / `update-oauth` supports an admin-group mapping decides whether the superadmin bit is declarative or a provisioning step. **Settle against the live binary's `--help`, not the docs** — same rule as R1, and note that `configure_oidc.py` already uses `update-oauth` for exactly this kind of change.
- **R6 — how does MinIO map an OIDC claim to a policy?** ADR-016 asserts MinIO "maps Authelia groups to MinIO policies" but nothing in this repo configures that mapping. Establish what the live instance actually does with the `groups` claim before claiming a tier is enforced there.

## Acceptance criteria

1. Gitea, MinIO and Grafana resolve their admin identity from a key of `apps.auth.identities`, and nothing resolves it from `BASIC_AUTH_USER`. Evidence is a live authentication per service, not a config diff.
2. The two tiers are real: `manu` performs an administrative action in each service where the tier is enforced, and `operator` is **refused** that same action while still able to do its day-to-day work. The refusal is half the evidence — a tier that only proves the permissive direction proves nothing. Where a service does not consume the group claim, that is recorded as a named gap with its issue, not silently passed over (Grafana → #951; Gitea and MinIO per R5/R6).
3. A user declared only in `apps.services.security.authelia.users` can log into Gitea through SSO and receives a working account, with no manual step in Gitea. Demonstrated with a throwaway identity that is removed afterwards, and the transcript captured.
4. Self-service registration remains closed: an unauthenticated attempt to register a Gitea account is refused. Demonstrated, not asserted from config.
5. An agent identity can be provisioned end to end from Ansible — account, scoped token, token in SOPS, login prohibited — and the resulting token can perform exactly the operations its scopes allow and is refused the ones they do not. The refusal is part of the evidence; a token that works proves only half the claim.
6. A test fails when a service's admin identity is resolved from anything other than the identity map. Same bar as the rest of this repo: demonstrated red before it is trusted green.
7. The break-glass path is exercised once per ADR-062 D4 — a local-password login while OIDC is unavailable — and documented in the runbook as exceptional. A break-glass path that has never been used is a hypothesis.
