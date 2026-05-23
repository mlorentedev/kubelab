---
id: "AI-001-ollama-public"
type: spec
status: draft
created: "2026-05-13"
tags: [spec, proposal, ai, traefik, ollama]
template_version: "1.0"
---

# AI-001: Expose Ollama publicly via Traefik with auth

## Why

KubeLab runs Ollama on the Beelink node (per ADR-028 operational topology). It is currently reachable only from LAN/Tailscale. Public exposure unlocks two things:

1. Personal LLM endpoint usable from any client (laptop, mobile, ai-workloads-starter demos).
2. Demo surface for the `ai-workloads-starter` content stream — without a public endpoint, the content claims to expose can't be substantiated.

Without this change, Ollama remains gated to homelab — half-finished from a content/strategy perspective.

Vault refs: `kubelab/30-architecture/adr-028-operational-topology.md`, `kubelab/11-tasks.md` (AI-001..005 stream).

## What

Add a new IngressRoute on the prod K3s Traefik:

- Hostname: `ollama.kubelab.live`
- Port: 443 (TLS via existing Cloudflare cert solver pattern)
- Backend: existing `ollama` external Service in K3s (already pointing at Beelink LAN IP)
- Auth: a Traefik middleware that requires a valid credential on every request (auth choice TBD — see Risks)

After this PR: `https://ollama.kubelab.live/api/*` is reachable from anywhere, returns 403 without auth, 200 with auth.

## Out of scope

- Rate limiting per IP / per token (tracked as AI-003).
- E2E test integration for staging/prod monitors (tracked as AI-002).
- Multi-tenant API key management (single shared key acceptable for v1).
- Token-usage metering / cost accounting.
- Auth for non-`/api/*` paths (Ollama exposes a UI on `/`; we expose only `/api/*` initially).

## Auth strategy — RESOLVED 2026-05-21 (see ADR-035)

**Decision:** X-API-Key via Traefik plugin `github.com/dtomlinson91/traefik-api-key-middleware` v0.1.2+. Plugin supports both `X-API-Key` and `Authorization: Bearer` headers (forward-compat with Stage 2 OIDC/JWT migration per ADR-035). API key lives in SOPS at `apps.services.ai.ollama.api_key`. Middleware CRD rendered from template + SOPS at deploy time via toolkit extension (AI-001 PR-B).

Rationale captured in vault `30-architecture/adrs/adr-035-api-auth-strategy.md`. Rejected: BasicAuth (misleading semantics), Authelia ForwardAuth (2-step token friction for ad-hoc clients), mTLS (cert distribution).

## Implementation split (3 PRs, linear deps)

| PR | Scope | Size |
|----|-------|------|
| **PR-A** (this spec finalize) | ADR-035 vault + AI-001 spec proposal/tasks/verification update + AI-002 fill | ~80 LOC docs |
| **PR-B** | Toolkit extension `apply_middleware_secrets()` + Ansible HelmChartConfig plugin registration + smoke | ~150 LOC |
| **PR-C** | K8s manifests (Middleware template + Secret + prod IngressRoute patch) + SOPS api_key + Makefile target + E2E test | ~100 LOC |

PR-A merges first (paves architecture); PR-B before PR-C (toolkit + plugin must be live before applying manifests).

## Risks / open questions

1. **No backend auth in Ollama itself.** If the middleware misconfigures or is bypassed, Ollama is open. Mitigation: also restrict Beelink Ollama port via Tailscale ACL (defense in depth).

3. **Cost/DoS exposure.** Even with auth, leaked key → expensive inference loop on Beelink GPU. AI-003 mitigates; until then key rotation costs <5 min so tolerable.

4. **Beelink concurrency.** Ollama serializes inference. Public endpoint may produce 502/timeout on burst. Acceptable initially; queueing is out of scope.

5. **No conflict with existing `ollama` external Service.** Verify in staging first that adding IngressRoute does not affect existing LAN reachability.

## Acceptance criteria

- [ ] `GET https://ollama.kubelab.live/api/tags` with valid auth returns 200 and lists installed models.
- [ ] Same request without (or wrong) auth returns 403 and does NOT reach Ollama (verify via Beelink access logs — zero new lines). Status code rationale: plugin `dtomlinson91/traefik-api-key-middleware` emits `403` for missing, invalid, or wrong-keyed requests per its README.
- [ ] `POST https://ollama.kubelab.live/api/generate` completes inference end-to-end and streams response.
- [ ] Existing prod E2E suite passes with zero regressions (no new failures on previously-passing services).
- [ ] Cert provisioned for `ollama.kubelab.live` via existing Cloudflare cert solver (no manual step).
- [ ] LAN/Tailscale access to Ollama via existing Service is unaffected (smoke from ace1 still works).

## References

- Vault: `10_projects/kubelab/11-tasks.md` — AI-001 entry
- ADR: `kubelab/30-architecture/adr-028-operational-topology.md`
- Sister specs: AI-002 (E2E coverage), AI-003 (rate limiting)
- Component: `kubelab/30-architecture/components/kubelab-agents.md`
