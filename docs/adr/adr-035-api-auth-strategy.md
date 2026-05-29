---
id: adr-035-api-auth-strategy
type: adr
status: active
created: "2026-05-21"
---

# ADR-035: Auth Strategy for Internal/Public APIs — X-API-Key Plugin v1, OIDC/JWT Roadmap

> **Date:** 2026-05-21
> **Status:** Accepted
> **Stakeholders:** Manu (sole operator)
> **Related:** AI-001 (first decision under this ADR), [adr-034-polyglot-apps-language-per-service](adr-034-polyglot-apps-language-per-service.md), [adr-028-operational-topology](adr-028-operational-topology.md)

## Context

The AI track (AI-001 Ollama public, AI-004 Pollex public, DT-004 widget-proxy, future kubelab-memory RAG endpoint) needs a consistent answer to "how does a non-browser client authenticate to an internal/public HTTP API". Existing kubelab auth surface is **Authelia OIDC** (browser SSO for Grafana, Argo CD, Gitea) — well-suited to UI flows but introduces two-step token exchange friction for `curl` / SDK / AI-agent clients.

AI-001 forced an explicit decision: BasicAuth | Authelia ForwardAuth | X-API-Key custom header | OIDC client_credentials + JWT | mTLS. Without an ADR, each new AI service would re-litigate the same choice and likely converge on inconsistent patterns.

## Decision

**API auth strategy is a two-stage roadmap, not a single point:**

**Stage 1 (NOW — `v1`)**: Per-service **X-API-Key custom header** via the Traefik plugin [`github.com/dtomlinson91/traefik-api-key-middleware`](https://github.com/dtomlinson91/traefik-api-key-middleware) v0.1.2+.

- Plugin registered once in K3s Traefik `HelmChartConfig.experimental.plugins` (same pattern as the existing CrowdSec bouncer plugin).
- One Middleware CRD per service (`api-key-ollama`, `api-key-widget-proxy`, …). Keys are inlined in the CRD — the toolkit renders the Middleware manifest from a template + SOPS at deploy time (analogous to how it already renders K8s Secrets from `REPLACE_WITH_SOPS_VALUE` placeholders).
- Plugin supports BOTH `X-API-KEY: <key>` AND `Authorization: Bearer <key>` headers (configurable, both enabled). The Bearer surface is the forward-compatibility hinge for the Stage 2 migration.
- API keys live in SOPS under `apps.services.<service>.api_key`, propagated via the toolkit secrets workflow.

**Stage 2 (FUTURE — trigger: kubelab-agents L1 lands OR multi-user/audit becomes a requirement)**: Migrate to **OIDC client_credentials grant** issued by Authelia + ForwardAuth middleware that introspects the bearer JWT.

- Each service registers an Authelia OIDC client (already the pattern for Argo CD / Gitea / Grafana).
- Clients exchange `(client_id, client_secret)` for a short-lived JWT, then send `Authorization: Bearer <jwt>` (the same header the Stage 1 plugin already accepts).
- Traefik Middleware swaps from `plugin: traefik-api-key-middleware` to `forwardAuth: authelia-introspect` — IngressRoute references stay identical, migration is per-service and additive.

**Anti-decisions explicitly captured here:**

- HTTP BasicAuth (RFC 7617): rejected as the primary mechanism. Functionally equivalent to X-API-Key with `user="apikey"`, but the wire-format semantics are misleading for API clients and the user/password convention forces an awkward fixed username. Acceptable as a one-off legacy fallback only.
- mTLS: rejected for HTTP API auth. Certificate distribution to ad-hoc clients (curl, IDE plugins, AI agents) is operationally hostile for a single-operator homelab.
- HMAC request signing (Stripe / AWS-style): rejected as over-engineered for the current threat model. Re-evaluate if a Stage 3 emerges (high-stakes write operations, signed payloads).
- Cloudflare API Shield / Workers: rejected on cost grounds.
- VPN-only (Tailscale gate): not a substitute for app-level auth on PUBLIC endpoints. Acceptable for staging-only services where the Headscale split DNS already provides the gate (e.g. current `ollama.staging.kubelab.live` has no auth — VPN gating is sufficient there).

## Consequences

- **Positive — Stage 1**: zero new identity infrastructure (plugin reuses existing Traefik). Per-service rotation via SOPS edit + redeploy. Universal client support (any HTTP client can set a header). Reusable factory pattern: a new AI service adds one Middleware + one SOPS entry, no architectural drift.
- **Positive — migration path**: the plugin's `Authorization: Bearer` mode means clients written today against X-API-Key Bearer header can transparently start receiving JWTs from Authelia tomorrow with zero client-side code change. The Middleware backend swap is invisible to consumers.
- **Negative — Stage 1**: keys are static (no built-in expiry). Compromised key requires manual rotation. Mitigated by short rotation cadence (quarterly) + monitoring (CrowdSec rate-limit + Traefik access logs surface anomalies). Stage 2 fixes this with JWT expiry.
- **Negative — Stage 1**: no per-user audit. The plugin only knows "valid key" or "not". For single-operator homelab this is acceptable; if a second operator or multi-user surface emerges, that is the Stage 2 trigger.
- **Negative — toolkit extension cost**: the toolkit needs a new capability to render Middleware manifests from SOPS templates (~50-80 LOC + tests). Spent once, reused for every future AI service. Tracked as part of AI-001 PR-B.

## Anchored decisions under this ADR

| Service | Stage | Mechanism | Status |
|---------|-------|-----------|--------|
| Ollama public (AI-001) | 1 | X-API-Key (dtomlinson91 plugin) | **Live 2026-05-23.** PRs #190 docs, #191/#192 spec-corrections, #193 toolkit+Ansible, #194 SOPS seed, #195 prod IngressRoute, #196 DNS, #198 RateLimit MVP (SEC-AI-001), #199 ace2 host networking (ANSIBLE-025). E2E verified: `ollama.kubelab.live` — 403 sin auth, 200 con `X-API-Key`/`Bearer`, rate-limit 60/min burst 10, in-flight cap 2. |
| widget-proxy (DT-004) | 1 | X-API-Key, same plugin | Pending spec impl |
| Pollex public (AI-004) | 1 | X-API-Key, same plugin | Pending |
| kubelab-memory RAG (future) | 2 | OIDC client_credentials + JWT | When L1 service lands |
| Argo CD / Gitea / Grafana / Authelia UI | n/a | Authelia OIDC (browser SSO) | Already deployed |

Future entries: append a row when a new auth-bearing service is added; link the spec/PR.

## Alternatives considered

| Option | Why rejected |
|--------|--------------|
| HTTP BasicAuth as primary | Misleading wire-format semantics for API keys; "user" field is dead weight; no per-key revocation. |
| Authelia ForwardAuth as primary | 2-step token-exchange friction for ad-hoc curl / SDK / agent clients in v1. Reserved for Stage 2 when service-to-service auth surfaces materialise. |
| mTLS | Operationally hostile for ad-hoc clients (cert distribution). |
| HMAC request signing | Over-engineered for current threat model; no replay-attack surface yet. |
| Cloudflare API Shield | Recurring cost not justified at this scale. |
| Per-key revocation via plugin keys list | Plugin reloads on Middleware update, but the SOPS-edit + redeploy round-trip is the rotation primitive. Acceptable for quarterly cadence. |

## Stage 2 migration trigger conditions

Re-open this ADR for Stage 2 migration when ANY of:

1. **kubelab-agents (L1 platform service) lands** with an HTTP control plane that calls multiple AI services — service-to-service auth makes a token broker pattern more natural than static keys.
2. **Multi-user access** is granted to any AI surface — per-user audit and revocation become first-class needs.
3. **Static API key leak incident** occurs — forces a re-evaluation of the rotation-cadence vs JWT-expiry tradeoff.
4. **Authelia OIDC introspection endpoint** matures enough to validate sub-100ms ForwardAuth latency at the per-request granularity expected by AI inference clients.

Until then, Stage 1 remains the canonical pattern; new AI services adopt the X-API-Key middleware factory.
