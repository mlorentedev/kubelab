---
id: "adr-062-platform-identity-model"
type: adr
status: accepted
created: "2026-08-14"
tags: [architecture, identity, authentication, authorization, ssot]
related:
  - adr-016-oidc-centralized-auth
  - adr-014-secrets-management-strategy
  - adr-038-secret-delivery-paths
  - adr-058-ace2-dev-node
  - adr-061-stateful-service-placement
issue: mlorentedev/kubelab#1013
owner: manu
---

# ADR-062: Platform Identity Model

## Status

Accepted — 2026-08-14. Tracks [#1013](https://github.com/mlorentedev/kubelab/issues/1013) (AUTH-004).

Complements [ADR-016](adr-016-oidc-centralized-auth.md), which decides *how* authentication is delivered (OIDC / forward-auth / bypass tiers) but never decides *who* the identities are or what privilege each one carries. This ADR fills that gap and does not supersede it.

Supersedes the single-identity decision recorded on #1013 earlier the same day — see [D0](#d0--what-this-reverses-and-why).

## Date

2026-08-14

## Context

The platform runs an identity provider and does not use it as the identity plane.

**Identity currently arrives by accident.** Gitea, Grafana and MinIO resolve their admin username from `BASIC_AUTH_USER` — a Traefik basic-auth secret with no semantic relationship to application identity (`toolkit/features/k8s_secrets.py:52`). Its value is the OS-level login, `manu`. Meanwhile `common.yaml` declares `apps.auth.admin_username: operator` as the SSOT. The two never met: authenticating against `gitea.kubelab.live` as `operator` returns `401`, as `manu` returns `200`.

**There is no way to express a privilege boundary.** Authelia defines exactly two groups, `admins` and `users`, and one human user who is in both. Argo CD is the only service that consumes them (`infra/helm/argocd/values.yaml:185` — `g, admins, role:admin` with `policy.default: role:readonly`). Everywhere else, "the admin" is a single account with total power and no lesser tier beneath it.

**There is no machine identity at all.** The only credential that exists is the human admin's password, so granting an agent access to a repository means handing it the operator's own account.

This became urgent because Gitea has just moved to the Beelink ([ADR-061](adr-061-stateful-service-placement.md)) and is about to receive real repositories. Identity decisions are cheap while it holds no content and expensive afterwards.

## Decision

### D0 — What this reverses, and why

An earlier decision on #1013, the same day, unified all application identity on a single name: `operator`, chosen as a role name that survives a change in who operates the platform, with `manu` deleted.

**Reversed.** One name cannot express a privilege boundary. It also produced the wrong shape in a second way: it would have left the platform with no accountable *named human* identity at all, only a role account that anyone might be behind. The correct separation is not "one name instead of two" — it is that a **person** and a **role** are different kinds of thing and should never have been collapsed into one account in the first place.

The original diagnosis survives intact and is what D3 fixes: the defect was never the *name* `manu`, it was that `manu` reaches three services through a basic-auth alias rather than by declaration.

### D1 — Four identity classes

| Class | Example | Authelia group | Privilege |
|---|---|---|---|
| **Named human** | `manu` | `admins` | Superadmin, per service |
| **Role account** | `operator` | `users` | Day-to-day operation; no administrative rights |
| **Machine** | `<agent>-bot` | none | Scoped token only; login prohibited |
| **Break-glass** | (see D4) | none | The IdP-unavailable path, and no other |

A named human account is personal and carries accountability: actions attributable to a person belong to an account named after that person. A role account is impersonal by design and therefore must not hold administrative power, because power without attribution is what makes a shared account dangerous.

### D2 — Groups are the privilege boundary; two of them

`admins` and `users`, the two that already exist. No third group is introduced until a concrete permission need appears that neither expresses. The existing tiers already fit the intended profiles: Argo CD gives non-`admins` `role:readonly`, and a normal Gitea user can own repositories and push — which is exactly the day-to-day profile `operator` needs.

### D3 — The identity SSOT is a map, and user entries reference it by key

Identity names are declared once, as a map:

```yaml
apps:
  auth:
    identities:
      superadmin: manu
      operator: operator
```

Every consumer resolves a name **through a key of this map**, never as a literal. This applies to the Authelia users list (an entry declares which identity it is, rather than carrying a hardcoded username), to both generators that build the user database, and to the three services that today resolve their admin from `BASIC_AUTH_USER`.

A map rather than two flat keys because the set is expected to grow — a second human, a machine class — and each growth should add a row, not a new key name for every consumer to learn.

`BASIC_AUTH_USER` itself is out of scope: it also feeds the Traefik basic-auth middleware, and retiring that consumer is separate work. What ends here is *application admin identity* depending on it.

### D4 — Break-glass is a second auth path on one account, not a second account

Each service's `manu` account holds a local password in SOPS **and** an OIDC link. SSO is the daily path; the local password is used when Authelia is unavailable, and at no other time.

The alternative — a distinct `breakglass` account per service — was rejected: it multiplies accounts that are rarely exercised, never audited, and each of which is a standing credential to rotate. One account with two authentication paths keeps a single identity to audit while preserving the escape hatch.

This does not weaken the existing rule that machine credentials (OIDC client secrets, service admin passwords) remain reversible in SOPS by design.

### D5 — Enforcement is per service, and must be verified live

"Superadmin everywhere via Authelia" is only true where the service actually consumes the group claim. Verified today: Argo CD does; Grafana does not ([#951](https://github.com/mlorentedev/kubelab/issues/951)); Gitea and MinIO are unverified.

Every claim about a service's group→role mapping is settled by testing against the running instance, not by reading documentation. A configuration that looks correct and silently grants the wrong tier is the failure this model exists to prevent, and it is indistinguishable from success on paper.

## Alternatives considered

**Single identity (`operator` only).** The decision this ADR reverses — see D0.

**Keep `manu` as the only identity.** Rejected. It leaves no impersonal account for day-to-day work, so every routine action runs with superadmin rights, and the platform has no tier to drop an agent or a second person into.

**A third `operators` group between `admins` and `users`.** Rejected as premature: no permission need has appeared that the existing two groups cannot express. Revisit when one does.

**Per-service `breakglass` accounts.** Rejected — see D4.

**An LDAP backend to hold the identity model.** Rejected for now. The model is two humans and a small set of bots; a directory service adds an always-on dependency in front of the IdP for a set that fits in a declared map.

## Consequences

### Positive

- A privilege boundary exists and is declarable. Routine work stops running as superadmin.
- Identity is resolved by declaration rather than inherited from a basic-auth secret, so a service's admin can be read off `common.yaml` instead of traced through the toolkit.
- Machine access no longer requires handing an agent a human's account.
- The Gitea rename pressure largely dissolves: `manu` survives as the declared superadmin, so no account is deleted and no repository ownership migrates. This is conditional on verifying what is attached to the existing account (SSH key, OIDC link, tokens) before relying on it.

### Negative

- Two human identities to maintain, with two password hashes in SOPS per environment instead of one.
- "Superadmin everywhere" is not true on day one. Grafana derives no role from groups (#951), and Gitea and MinIO are unverified — so the model is declared before it is fully enforced.
- Every consumer that resolves an identity gains an indirection through the map. That is the point, but it is a change in more than one generator.

### Risks

- **A tier that is not enforced is theatre.** If `operator` logs into a service that ignores the group claim, it silently gets whatever that service's default is — possibly admin. The model is only worth its complexity if a test fails when a service resolves identity or privilege from anything other than the SSOT.
- **Break-glass drifts into daily use.** A local password that works is a path of least resistance when SSO is slow. The mitigation is that it is documented as exceptional and its use is visible, not that it is inconvenient.

## References

- [ADR-016](adr-016-oidc-centralized-auth.md) — OIDC delivery tiers (how auth is delivered).
- [ADR-014](adr-014-secrets-management-strategy.md), [ADR-038](adr-038-secret-delivery-paths.md) — where credentials live and how they reach a service.
- [ADR-061](adr-061-stateful-service-placement.md) — Gitea's placement, which set this work's deadline.
- `specs/AUTH-004-identity-and-machine-access/` — the implementation spec.
- [#1013](https://github.com/mlorentedev/kubelab/issues/1013) — the tracking issue, and the decision record this ADR reverses.
- [#951](https://github.com/mlorentedev/kubelab/issues/951) — Grafana derives no role from Authelia groups.
- [#952](https://github.com/mlorentedev/kubelab/issues/952) — no way to enumerate identities across the five planes.
