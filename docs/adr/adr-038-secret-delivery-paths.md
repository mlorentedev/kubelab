---
id: adr-038-secret-delivery-paths
type: adr
status: active
created: "2026-05-25"
---

# ADR-038 — Secret delivery paths: three mechanisms, one SSOT

## Status

**Accepted** — 2026-05-25. Documents current state and evaluates future unification (Sealed Secrets).

## Context

A secrets-architecture review on 2026-05-25 surfaced the question: "Do I have two secret mechanisms? Should I unify them?"

After audit, the answer is: **one SSOT (SOPS), three delivery paths to pods**, dictated by Kubernetes API limitations and per-service config consumption patterns. They are not duplication — they are different mechanisms for technically-different situations.

### Path 1 — K8s Secret with envFrom

- **Catalog**: `SECRET_CATALOG` in `toolkit/features/secrets_manager.py` + `SecretMapping` in `toolkit/features/k8s_secrets.py`.
- **CLI**: `make apply-secrets ENV=<env>` → `toolkit infra k8s apply-secrets`.
- **Flow**: SOPS `*.enc.yaml` → in-memory decryption → `kubectl apply` of a K8s `Secret` object → pod consumes via `envFrom: secretRef`.
- **Use cases**: passwords, API keys, `jwt_secret`, `oidc_hmac_secret`, OIDC client secrets — anything the target service reads as env vars.

### Path 2 — Traefik Middleware with embedded secret

- **Catalog**: `MIDDLEWARE_CATALOG` in `toolkit/features/k8s_middlewares.py`.
- **CLI**: `make apply-middleware-secrets ENV=<env>`.
- **Flow**: SOPS → render Jinja template (`*.yaml.tpl`) → `kubectl apply -f -` via stdin → Traefik `Middleware` CRD with the secret embedded literal in the manifest.
- **Use cases**: Ollama API key (post-AI-001 / ADR-035).
- **Why a separate path**: the Traefik Middleware CRD does **not** support `secretKeyRef` (or any indirection to a `Secret` object) for its API-key value field. The literal must live in the manifest. To keep plaintext off persistent disk, the rendered manifest is piped through stdin and the gitignored audit copy lives only in the working tree.
- **Per CLAUDE.md gotcha**: Middlewares with embedded secrets are NOT in Kustomize or git.

### Path 3 — K8s Secret with multi-line file value (config-as-file)

- **Use cases**: Authelia `configuration.yml` + `users_database.yml`, and any future service that reads its full config from a file rather than env vars.
- **Flow**: SOPS → render Jinja template → embed the entire rendered config as a single `data:` key inside a K8s `Secret` → pod mounts via `subPath: configuration.yml` into `/config/`.
- **Why a separate path**: Authelia (and similar services) read configuration from disk, not env vars. The config itself contains plaintext secrets inline (`jwt_secret`, argon2 hashes, OIDC client secrets), so it cannot be a `ConfigMap`. It must be a `Secret`, and it must be a single multi-line value, not a key-per-secret map.

### The SSOT is already unified

All three paths start from the same SOPS-encrypted `*.enc.yaml` files under `infra/config/secrets/`. There is no parallel secret store, no separate key material, no out-of-band injection. The toolkit is the single decryption boundary; pods see decrypted values only at the K8s API surface (Secret object) or, for Path 2, only inside the Middleware CRD applied via stdin.

What is **not** unified is the user-facing CLI (`make apply-secrets` + `make apply-middleware-secrets`) and the catalog format (`SECRET_CATALOG` vs `MIDDLEWARE_CATALOG`). That is a UX issue, not an architectural one.

## Decision

**Keep the three delivery paths as separate mechanisms.** They are forced by K8s API asymmetries and per-service config-consumption patterns — collapsing them would require either dropping K8s features the project uses (Traefik Middlewares, Authelia file-based config) or building heavy adapters (sidecars, init-containers) that add operational surface without removing the underlying complexity.

**Unify the user-facing CLI** as a separate follow-up: a single `make apply-secrets ENV=<env>` target that internally fans out to all three paths. The current `apply-middleware-secrets` becomes a deprecated alias. Single command, three internal mechanisms — the right ergonomic shape.

**Defer Sealed Secrets evaluation** until GitOps maturity reaches the point where in-cluster controller-based decryption is operationally attractive (tracked as SEAL-001..004 in the broader backlog; conditional on Argo CD Image Updater and post-ADR-037 prod-side validation being settled). Sealed Secrets would replace SOPS as the at-rest format and would make Path 1 and Path 3 a single declarative resource in git, but **would not eliminate Path 2** (the Traefik Middleware CRD limitation persists regardless of secret-store choice). The unification gain is partial; the migration cost is large.

## Consequences

### Positive

- Each delivery path is **fit-for-purpose** and minimal. There is no per-service hack-on-top-of-hack to force one mechanism to do another's job.
- Plaintext **never touches persistent disk that is committed** — generated configs containing plaintext (Authelia, Middlewares) are gitignored; what is committed is either encrypted (`*.enc.yaml`), templates (`secrets.yaml` with `REPLACE_WITH_SOPS_VALUE` placeholders), or non-secret values (`common.yaml`).
- The SSOT-only-in-SOPS rule is intact: any new secret has exactly one source-of-truth location, and the toolkit decides which delivery path to use based on its catalog entry.

### Negative / accepted

- New developers must learn three patterns, not one. Mitigated by:
  - This ADR as the canonical map.
  - The two catalogs (`SECRET_CATALOG`, `MIDDLEWARE_CATALOG`) carry self-describing entries with comments pointing at this ADR.
- Adding a new auth-protected service requires touches in **three** places (`SECRET_CATALOG`, `MIDDLEWARE_CATALOG`, a `.yaml.tpl` file) per ADR-035. Mitigated by the catalog pattern keeping each touch small and template-driven, but it is more verbose than a single declarative resource would be.

### Future unification path (deferred, not rejected)

Sealed Secrets (SEAL-001..004 backlog) would:
- Replace SOPS as the at-rest format with `SealedSecret` CRDs committed to git.
- Eliminate the toolkit decryption step from CI/CD — the in-cluster controller decrypts on apply.
- Unify Path 1 and Path 3 into "apply the SealedSecret manifest, controller emits Secret, pod consumes".

Sealed Secrets would **not**:
- Eliminate Path 2 (Traefik Middleware CRD has no indirection regardless of secret-store choice).
- Remove the need for per-service catalog entries (the catalog moves from "where the SOPS key lives" to "which K8s resource is generated", but the catalog itself remains).

Trigger to revisit: Argo CD Image Updater landed (ARGO-014) **and** ADR-037 prod-side validation has run a few real promotions **and** the project has more than ~3 contributors (the catalog-touch overhead becomes proportionally more painful with team size).

## Alternatives considered

### A1 — Sealed Secrets now

Rejected. Migration cost (re-encrypt all secrets with cluster pubkey, rotate every Authelia/Gitea/N8N/MinIO password, write `SealedSecret` for every existing K8s Secret, update toolkit, retire SOPS) is multi-day. Marginal benefit while the project has a single operator and CI does not need access to most secrets. Revisit per the trigger above.

### A2 — External Secrets Operator + Vault/AWS Secrets Manager

Rejected. Adds an external secret-store dependency (operationally heavier than SOPS, which has zero runtime dependencies). Still does not solve Path 2 (Traefik Middleware CRD limitation). The cost/benefit is worse than Sealed Secrets for a single-operator personal lab.

### A3 — Sidecar / init-container that templates Authelia config from envs

Rejected for Authelia specifically. Would let Path 3 collapse into Path 1 (Secret of env vars + sidecar that renders config from envs at startup). But: adds a custom container image to maintain, doubles Authelia's pod surface, and Authelia's own config schema is rich enough that a templating sidecar becomes its own mini-system. The current approach (toolkit renders config, applies as Secret) keeps complexity at build time where it can be tested deterministically.

## Cross-references

- **ADR-030** — Self-hosted CI runner on Beelink (related: where the age key lives for `apply-secrets`).
- **ADR-035** — Three-PR rollout pattern for AI-001 (introduced Path 2 with the api-key middleware).
- **ADR-036** — Shared infra namespace (related: SSOT-012 cleanup of SOPS-sourced non-secrets that previously leaked into ConfigMaps).
- **CLAUDE.md "Critical gotchas"** — entries on Authelia OIDC JWKS, Middleware secret injection, K8s ConfigMaps MUST NOT contain SOPS values, and Authelia secrets key path all manifest one of the three paths.
- **SECRET_CATALOG** (`toolkit/features/secrets_manager.py`) — Path 1 + Path 3 registry.
- **MIDDLEWARE_CATALOG** (`toolkit/features/k8s_middlewares.py`) — Path 2 registry.
- **SEAL-001..004** (backlog) — deferred Sealed Secrets evaluation; revisit conditional on triggers above.
