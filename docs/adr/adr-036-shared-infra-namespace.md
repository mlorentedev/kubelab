---
id: "adr-036-shared-infra-namespace"
type: adr
status: accepted
created: "2026-05-23"
tags: [architecture, ssot, microservices, stream-c]
related: [adr-023-hub-spoke-multicloud-gitops](adr-023-hub-spoke-multicloud-gitops.md)
---

# ADR-036: Shared Infra Services Namespace Convention

## Status

Accepted — 2026-05-23

## Context

Pre-2026-05-23 the SMTP configuration (`email_user`, `email_pass`, `email_host`, `email_port`, `email_from`) lived under `apps.platform.api.*` in `common.yaml` and SOPS. The API consumed it as expected. Authelia, however, ALSO consumed `APPS_PLATFORM_API_EMAIL_USER` and `APPS_PLATFORM_API_EMAIL_PASS` for SMTP notifications — by cross-reading from a namespace that semantically belonged to a different service.

This is a layering violation that surfaces as concrete pain when planning Stream C (repo separation). When `apps.platform.api` graduates to its own repo, Authelia loses its SMTP source unless the namespace is restructured first.

The same pattern will repeat any time a "shared infrastructure service" (SMTP, future shared Redis, future shared object storage, etc.) is consumed by more than one logical service.

SSOT-012 surfaced this gap during the toolkit's `SECRET_PATTERNS` regex audit — non-secret values (display names, public IDs) were being treated as secrets because their flattened env var names didn't match the `PASS|PASSWORD|SECRET|TOKEN|KEY|CREDENTIALS|AUTH|JWT|CLIENT` regex, so they leaked from SOPS into committed ConfigMaps. The cleanup forced a decision about where shared infra values belong.

## Decision

Establish `infra.<service>.*` as the canonical top-level namespace for any value consumed by more than one component.

Specifically:

1. **Namespace**: shared infrastructure values live at `infra.<service-name>.<attribute>` in `infra/config/values/common.yaml` (or env-specific overrides). Examples that fit:
   - `infra.smtp.user`, `infra.smtp.host`, `infra.smtp.port`, `infra.smtp.from`, `infra.smtp.pass` (last one in SOPS)
   - Future: `infra.redis.*`, `infra.s3.*`, `infra.ntp.*`

2. **Flattening**: `infra.smtp.user` flattens to env var `INFRA_SMTP_USER` (uppercase, `_` separator). The flattened name is the **canonical contract** — consumers in source code, Compose substitutions, and Jinja templates all reference this exact name.

3. **No prefix stripping for shared namespace**: unlike per-component config under `apps.platform.<component>.*` (which is stripped to a component-local view, e.g., `APPS_PLATFORM_API_EMAIL_USER` → `EMAIL_USER` in the API pod), shared values are emitted **with the full prefix preserved**. This is intentional: `INFRA_SMTP_USER` is a clear cross-cutting identifier; bare `SMTP_USER` would be ambiguous (which SMTP server? whose user?).

4. **Generator behavior**: `toolkit/features/generator_k8s.py:_build_configmap_env_vars` picks up two prefix classes:
   - `APPS_PLATFORM_<COMPONENT>_*` — stripped to component-local names (existing behavior, unchanged)
   - `INFRA_*` — emitted as-is into every component's ConfigMap that wants shared infra access

5. **Secrets stay in SOPS, non-secrets in `common.yaml`**: same rule as before. `infra.smtp.pass` lives in SOPS; `infra.smtp.user/host/port/from` live in `common.yaml`.

6. **Authelia and other Jinja-rendered services**: their templates reference the canonical name `{{ INFRA_SMTP_USER }}`. The toolkit `ConfigurationManager.get_env_vars()` injects all flat env vars including the `INFRA_*` ones.

## Consequences

**Positive**:

- **Stream C extraction is trivial for shared infra consumers**: when `apps.platform.api` graduates to its own repo, the API's SMTP config travels with it under `infra.smtp.*` (or the new repo points to a config bundle that includes the shared namespace). Authelia is unaffected because it reads from `infra.smtp.*` directly.
- **Pattern scales to new shared services**: future shared Redis, shared object store, shared NTP — each gets a flat `infra.<service>.*` block in `common.yaml` and is picked up by every consumer. No further generator changes needed.
- **Eliminates cross-namespace coupling**: no more "Authelia reads from API's namespace" or vice versa. Clear ownership boundaries.
- **Closes the `SECRET_PATTERNS` regex gap for shared values**: explicit separation between SOPS-stored secrets (`infra.smtp.pass`) and `common.yaml`-stored config (`infra.smtp.user` etc.). The audit-revealed leak (PR #208 + #209 + this one) is now structurally impossible.

**Negative / accepted tradeoffs**:

- **`INFRA_*` is global per ConfigMap**: every component's ConfigMap includes ALL `INFRA_*` values, not just the ones it consumes. Mild bloat. Acceptable because (a) shared infra is small in volume, (b) the alternative — per-component opt-in declarations — adds plumbing without clear benefit.
- **One-time consumer code churn**: API Go (`apps/api/src/pkg/config/env.go`), Compose substitutions, Authelia template all rename from `EMAIL_*` to `INFRA_SMTP_*`. ~10 lines across 3 files. Net negative LOC in toolkit (removing `SECRET_CATALOG` entries that no longer apply).
- **Tests need a one-time refresh**: any test that asserts on the old env var name needs updating. Audit during the implementation PR.

## Alternatives Considered

**A. Keep `apps.platform.api.email_*`, document Authelia coupling as known debt.** Lowest immediate cost (~15 LOC, mirrors PR #208/#209). Rejected because the debt is concretely load-bearing for Stream C — Authelia's SMTP source disappears at extraction time, requiring a future emergency refactor.

**B. Backward-compat alias layer in toolkit (`INFRA_SMTP_USER` → `EMAIL_USER`).** Preserves API code unchanged. Rejected because the alias layer becomes magic that future developers must understand to trace the flow. "Easy to add a new service" becomes "easy to add a new service IF you know the alias rules". Inconsistent.

**D. Move SMTP under `apps.services.shared.smtp.*` (extend existing `apps.services.*`).** Considered but rejected: `apps.services.*` historically holds platform-internal services (Authelia, Grafana, MinIO) with their own deployment manifests, NOT shared external-config blocks like SMTP. Stretching the namespace would muddy its meaning. `infra.*` as a NEW top-level is semantically cleaner.

## Implementation

Landing PR: **SSOT-012 PR #3** (`fix/ssot-012-shared-smtp-c1`). Atomic touches in one PR to avoid intermediate broken states:

- This ADR document
- `toolkit/features/generator_k8s.py` — `_build_configmap_env_vars` extension
- `infra/config/values/common.yaml` — new `infra:` top-level block
- `infra/config/secrets/common.enc.yaml` — `email.{user,pass}` → `infra.smtp.{user,pass}`
- `toolkit/features/secrets_manager.py` — `SECRET_CATALOG` paths updated
- `toolkit/features/k8s_secrets.py` — `SECRET_MAPPING` renamed
- `infra/k8s/overlays/{staging,prod}/secrets.yaml` — placeholders renamed
- `apps/api/src/pkg/config/env.go` — `os.Getenv` calls renamed
- `infra/stacks/apps/api/compose.base.yml` — env var substitutions renamed
- `infra/config/authelia/templates/configuration.yml.j2` — Jinja references renamed
- `CLAUDE.md` (repo) — new gotcha entry "Shared infra services use `infra.<service>.*` namespace pattern"

## Future Work

When the next shared infra service surfaces (e.g., shared Redis as decided in adr-027-intelligence-layer phase 2), the implementation pattern is:

1. Add `infra.<service>.{attributes}` to `common.yaml` (or SOPS for secrets).
2. Consumers reference `INFRA_<SERVICE>_<ATTR>` env var directly (no toolkit changes needed; the generator extension already picks it up).
3. ADR not required for the addition itself — this ADR establishes the pattern; new uses inherit it.

## References

- SSOT-012 PR #1 [#208](https://github.com/mlorentedev/kubelab/pull/208) — first audit-driven move
- SSOT-012 PR #2 [#209](https://github.com/mlorentedev/kubelab/pull/209) — second move, surfaced the Authelia coupling
- Audit consumer table (2026-05-23) — 21 references across 9 files informed this decision
- CLAUDE.md gotcha "K8s ConfigMaps MUST NOT contain SOPS-sourced values" — the original rule that this ADR operationalizes via clear namespace ownership
- Stream C (Repo Separation) backlog — TOOLKIT-*, PUB-*, PLAT-* tickets depend on clean per-app namespaces, which this ADR enables
