---
id: lesson-368-internal-telemetry-requires-vpn-gated-ingress-and-token-aware-traceback-deduplication
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: observability
tags: [kubelab, observability, loki, traefik, agents, triage, security]
---

# Internal telemetry requires VPN-gated ingress and token-aware traceback deduplication

**Context**: Implementing agentic observability tooling (`toolkit obs`) and automated SRE incident auto-triage to allow human operators and AI agents to query cluster telemetry directly from Tailscale VPN mesh without manual port-forwards (ADR-064).

**Problem**: 
1. Connecting directly to cluster host ports (e.g. `http://100.64.0.2:3100`) failed with `Connection refused` because in Kubernetes (K3s), service ports listen on internal overlay ClusterIPs (`10.43.0.0/16`), not on host machine sockets. Requiring manual `kubectl port-forward` commands breaks automation and agent autonomy.
2. Raw log streams contain hundreds of repetitive multi-line exception stack traces, which rapidly exhaust LLM token context windows during incident triaging if not deduplicated.

**Solution**:
1. Added a Traefik `vpn-whitelist` Middleware restricting access strictly to the Tailscale subnet (`100.64.0.0/10`) and configured a dual-route IngressRoute for Loki (`infra/k8s/base/services/loki.yaml`). Requests carrying `Authorization: Bearer <token>` bypass Authelia SSO redirects to serve automated agents directly, while unauthorized browser sessions redirect to 2FA.
2. Built fingerprint-based traceback normalization in `deduplicate_tracebacks()` supporting bracketed timestamps `[%Y-%m-%d %H:%M:%S]` and ISO-8601 formats, replacing repeated bursts with `[Repeated Nx]` count badges.

**Rule**: Never expose raw Kubernetes ClusterIP services via ad-hoc host ports or port-forwards. Standardize internal API ingress routes guarded by VPN IP-whitelists and Service Account Bearer Tokens, and always compress repetitive telemetry streams before handing them to LLM agents.

**Tags**: `#observability` `#loki` `#agents` `#pr-1319`
