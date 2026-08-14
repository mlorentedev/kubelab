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

## Why

<!-- from issue #1013: AUTH-004: MinIO and Gitea admin usernames still 'manu', aliased through a Traefik basic-auth secret -->

Three separate gaps share one cause: the platform has an identity provider and does not actually use it as the identity plane.

1. **Two names for one person.** Authelia authenticates the operator as `operator` (`apps.auth.admin_username`, the declared SSOT). Gitea, MinIO and Grafana know the admin as `manu` — `k8s_secrets.py` maps their `ADMIN_USER` to `BASIC_AUTH_USER`, which resolves to the OS-level login. Verified live: authenticating against `gitea.kubelab.live` as `operator` returns `401`; as `manu`, `200`. This is #1013, open since 2026-08-12.

2. **SSO cannot onboard anyone.** Read from the live `app.ini` on the Beelink: `[service] DISABLE_REGISTRATION = true`, and **no `[oauth2_client]` section at all**, so OIDC auto-registration sits at its default of off. A new collaborator would authenticate against Authelia successfully and then be refused by Gitea for having no account. Adding a person today therefore means creating a local account by hand — the non-reproducible path this project rejects everywhere else.

3. **No machine identity at all.** There is no pattern for giving an agent access to a repository. The only credential that exists is the human admin's password, so "let an agent work in Gitea" currently means handing it the operator's own account.

**The window matters, and it closes by itself.** Gitea holds 0 repositories and 1 user right now (captured under `AC4-EVIDENCE` in the ADR028-004 spec). Renaming the admin today is a config change plus one `gitea admin user delete`. After the first push it becomes a repository-ownership migration, because Gitea's CLI has **no `rename` subcommand** — verified against the live binary: `list`, `change-password`, `delete`, `generate-access-token`, `must-change-password`, and nothing else. The operator's first push is what closes the cheap window.

## What

- **One identity name.** `operator` — a role name, not a person's name, so it survives a change in who operates the platform. Decided by the operator on 2026-08-14 and recorded on #1013 with the rejected alternatives. Gitea, MinIO and Grafana stop resolving their admin from `BASIC_AUTH_USER` and resolve it from `apps.auth.admin_username` instead.
- **SSO is the human login path.** OIDC auto-registration enabled so that declaring a user in `apps.services.security.authelia.users` (plus their argon2 hash in SOPS) is the whole of "add a person" — users as code. Self-service registration stays closed.
- **Break-glass, explicitly.** Each service keeps a local admin credential, random and SOPS-held, documented as the path used when the IdP is unavailable and at no other time. This is what stops "one identity" from meaning "one password reused".
- **A machine-identity pattern.** A dedicated Gitea account per agent — never a shared human account — with a scoped access token minted reproducibly by `gitea admin user generate-access-token --username <bot> --token-name <n> --scopes <read|write>:<block>` from Ansible, and the token registered in `SECRET_CATALOG`. Deploy keys for single-repository access, where a token would be wider than needed.

## Out of scope

- **Renaming the OS-level user.** `networking.ssh_users.homelab` is `manu` and stays `manu`. It is a different concept from the application identity — CLAUDE.md's SSOT-014 section already draws this distinction — and changing it is a per-node migration tracked separately as `SSH-RENAME-001`.
- **Argo CD and Authelia's own admin accounts.** Both already resolve from the SSOT; this spec only covers the three services aliased through `BASIC_AUTH_USER`.
- **Retiring `BASIC_AUTH_USER` itself.** It also feeds the Traefik basic-auth middleware. Removing that consumer is a separate change; this spec only stops the three service admins from depending on it.
- **Onboarding an actual second human or agent.** This spec builds the path and proves it with a throwaway identity; using it is not a deliverable.

## Risks / open questions

- **R1 — which flag combination actually enables OIDC-only onboarding.** Two candidates: `oauth2_client.ENABLE_AUTO_REGISTRATION=true`, or `DISABLE_REGISTRATION=false` together with `ALLOW_ONLY_EXTERNAL_REGISTRATION=true`. The docs describe both mechanisms without stating how they interact when registration is disabled globally. **Must be settled by testing against the live instance, not by reading** — create a throwaway Authelia user, attempt an SSO login, observe. Guessing here produces a config that looks right and silently refuses people.
- **R2 — does the rename cost anything beyond the account?** Gitea has 0 repos, so nothing is owned. But the OIDC linkage, the registered SSH key and any existing token are attached to `manu`'s user id. Confirm what survives a delete-and-recreate versus what must be re-registered; the SSH key at minimum will need re-adding.
- **R3 — Grafana and MinIO are not empty in the same way.** Gitea's rename is cheap because it has no content. Grafana owns dashboards and MinIO owns buckets, both possibly attributed to the current admin. Check ownership before assuming the same delete-and-recreate applies, and treat them as separate tasks if it does not.
- **R4 — does an agent account need to be invisible to SSO?** A bot account authenticating with a token should not also be able to log in through Authelia. Decide whether that is enforced (`prohibit_login`, or simply never declaring it in Authelia) or merely conventional.

## Acceptance criteria

1. Authenticating against Gitea, MinIO and Grafana as `apps.auth.admin_username` succeeds, and the old `manu` application accounts no longer exist. Evidence is a live response per service, not a config diff.
2. A user declared only in `apps.services.security.authelia.users` can log into Gitea through SSO and receives a working account, with no manual step in Gitea. Demonstrated with a throwaway identity that is removed afterwards, and the transcript captured.
3. Self-service registration remains closed: an unauthenticated attempt to register a Gitea account is refused. Demonstrated, not asserted from config.
4. An agent identity can be provisioned end to end from Ansible — account, scoped token, token in SOPS — and the resulting token can perform exactly the operations its scopes allow and is refused the ones they do not. The refusal is part of the evidence; a token that works proves only half the claim.
5. A test fails when a service's admin identity is resolved from anything other than the SSOT. Same bar as the rest of this repo: demonstrated red before it is trusted green.
