---
id: "DT-004-widget-proxy"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-05-20"
tags: [spec, proposal]
template_version: "1.0"
---

# DT-004-widget-proxy

> **Naming**: file lives at `<repo>/specs/DT-004-widget-proxy/proposal.md`. `DT-004-widget-proxy` is `YYYY-MM-DD-<slug>` or `<TICKET-NN>`.

## Why

<!-- from 11-tasks.md: Server-side health checks — evaluate Homepage `/api/ping` or proxy. Current `fetch(no-cors)` can't distinguish 200 from 500. -->

The Homepage cockpit uses `fetch(..., {mode: 'no-cors'})` to ping services from the browser. The response is `opaque` — the browser cannot read the status code, so HTTP 200, 500, and timeouts all render identically as "up". Tiles show green even when the service is broken, and any service behind Authelia is doubly unreachable because the browser cannot traverse the auth redirect. Result: the cockpit is unreliable for daily operation; we cannot trust it as a signal during incidents, which defeats its purpose.

## What

After this PR, three things exist that did not before:

1. **`widget-proxy` microservice** running in the `kubelab` namespace on K3s — a minimal Go (or Python aiohttp) HTTP server (~target ≤200 LOC) that performs server-side health checks against a curated list of internal services. Reads target list from a ConfigMap generated from `common.yaml` SSOT.

2. **HTTP API `GET /health?target=<service-name>`** that returns JSON
   `{ "status": "up" | "down" | "degraded", "code": <http-status-int>, "latency_ms": <int> }`.
   `up` = 2xx, `degraded` = 3xx/4xx (excluding 401/403 if expected behind auth), `down` = 5xx / timeout / connection refused. Server-side fetch reads the real status code (no `no-cors` opacity). Auth-protected services are reached via internal cluster DNS so Authelia is bypassed end-to-end between proxy and service.

3. **Homepage cockpit migration** — `infra/k8s/base/services/homepage-templates/services.yaml.j2` switches the affected tiles from `ping:` (browser-side `fetch(no-cors)`) to `widget: { type: customapi, url: https://widgets.staging.kubelab.live/health?target=... }`. Tile color now reflects the real upstream status.

## Out of scope

- **Prometheus + `node_exporter` migration** — [[DASH-DT-015]] covers the durable enterprise observability path. `widget-proxy` is the tactical bridge that fixes the cockpit signal while DT-015 is in flight; it gets replaced (not extended) when Prometheus lands.
- **Advanced widget semantics** — latency histograms, SLO burn-rate, alert routing, multi-target aggregation (`/health/all`), batched requests. v1 emits `up | down | degraded` + status code + latency_ms. Anything richer goes to DT-015 / Grafana.
- **Auth federation / OIDC client inside the proxy** — v1 reaches auth-protected services via internal cluster DNS (Authelia is bypassed end-to-end between proxy and the service pod). The proxy does not implement OIDC client credentials or token exchange. If a target requires real auth (rare), it gets a `degraded` status with a documented `auth_required` note instead of a passing tile.

## Risks / open questions

- **[RESOLVED 2026-05-20] Language choice → Go**. Repo is already polyglot (`apps/api` is Go + Gin + zerolog with Dockerfile multistage `golang:1.25-alpine`). Use case (lightweight HTTP proxy) is a sweet spot for Go stdlib `net/http`. Image ~5 MB scratch + static binary. Sets precedent that new microservices live under `apps/*` and pick the language that fits the service (vs forcing everything Python). Toolkit Python stays for CLI / generators / orchestration.
- **[RESOLVED 2026-05-20] Target list source → ConfigMap generated from `common.yaml` SSOT**. A new toolkit script (sibling of `sync_homepage_config.py`) renders `apps.services.*` into a `widget-proxy-targets` ConfigMap. Proxy mounts the ConfigMap at startup and refreshes via filesystem watch (or restart on rollout). No K8s API runtime coupling, no hardcoded YAML in the image. Adding a target = edit `common.yaml`, run `make sync-widget-proxy-targets`, redeploy.
- **[OPEN, non-blocking] Auth-protected target semantics**: when a target returns 401 from an Authelia ForwardAuth layer (rare — proxy uses internal cluster DNS to bypass), do we report `degraded` with a `auth_required` flag (yellow tile) or `down` (red tile)? Default to `degraded` and refine after first live smoke; the choice is reversible and does not block the spec.

## Acceptance criteria

- [ ] **AC1**: `widget-proxy` deploys to K3s as Deployment + Service + IngressRoute in the `kubelab` namespace. `kubectl get pods -n kubelab -l app=widget-proxy` shows ≥1 replica `Running` with `Ready 1/1`. Liveness/readiness probes pass.
- [ ] **AC2**: `curl -s https://widgets.staging.kubelab.live/health?target=grafana` returns valid JSON matching the schema `{status: "up"|"down"|"degraded", code: <int>, latency_ms: <int>}`. The reported status matches K8s reality — scaling the upstream pod to 0 replicas flips the response to `down` within one health-check interval; scaling back to 1 returns to `up`.
- [ ] **AC3**: Homepage cockpit `services.yaml.j2` migrates ≥3 representative tiles from `ping:` to `widget: { type: customapi, ... }`. After `make sync-homepage` + `make deploy-k8s ENV=staging`, the visual cockpit shows green / red / yellow tiles that match each target's actual state (manual browser check on `home.staging.kubelab.live`). Refresh interval ≤ current `ping` interval.
- [ ] **AC4**: Toolchain stays green — `make sync-homepage` regenerates `services.yaml` byte-equal to the manually-replicated output (only Cloudflare `date_gt:` may auto-bump). `make test` reports 91+ tests passing. `make lint` clean. No regression in any existing widget.
- [ ] **AC5**: **Incident drill** — `kubectl scale -n kubelab deploy/<target> --replicas=0`; within 60 s (or the configured refresh interval, whichever is larger) the corresponding cockpit tile turns red. Scaling back to 1 returns it to green within the same window. Validates end-to-end signal correctness, not just the HTTP path.
- [ ] **AC6**: **TLS + Let's Encrypt cert** — the IngressRoute at `widgets.staging.kubelab.live` uses `certResolver: letsencrypt` (same pattern as every other public service per CLAUDE.md gotcha). `curl -v` shows a valid LE chain, no self-signed fallback.
- [ ] **AC7**: **CrowdSec bouncer + rate limit** — the IngressRoute attaches the `crowdsec-bouncer` middleware (Traefik plugin, same pattern as `grafana` / `gitea` IngressRoutes) and a per-IP rate limit middleware. `widget-proxy` is read-only and tiny but it is on the public edge; abuse protection is non-negotiable. Verified by hammering `/health?target=...` with `hey -n 1000 -c 100`: 200s under the limit, 429s above it.

## References

- Vault: `10_projects/kubelab/11-tasks.md` — DASH-DT-004 (this spec) + DASH-DT-015 (Prometheus migration, supersedes this work eventually).
- Related ADR: ADR-032 (observability stack execution) for the broader context of how cockpit / Glances / Prometheus fit together.
- Related patterns: `00_meta/patterns/pattern-spec-driven-development.md` (this spec follows it); CrowdSec bouncer + LE cert patterns are documented in CLAUDE.md gotchas.
- Sister specs in `specs/archive/` for tone — `DT-014-glances-coverage/` (Ansible role pattern), `TOOL-006-argo-revision-cli/` (toolkit CLI pattern).
