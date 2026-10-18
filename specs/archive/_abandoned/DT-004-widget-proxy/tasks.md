---
tags: [spec, tasks, kubelab, observability]
created: "2026-05-20"
---

# Tasks - DT-004-widget-proxy

> Atomic implementation breakdown. Each task = one focused commit when feasible; T3 may span a few commits because K8s manifests are interdependent. Targeting ≤300 net LOC across the PR per Atomic PR discipline.

## Setup

- [ ] Branch created from master: `feat/DT-004-widget-proxy`
- [x] `proposal.md` complete, AC1–AC7 testable
- [x] Both BLOCKERS resolved (language = Go; target list = ConfigMap from `common.yaml`)
- [ ] `make sync-homepage` clean baseline on master (no surprise diffs)

## T1 — Go service skeleton + health check core (~120 LOC)

- [ ] `apps/widget-proxy/` created with Go module
  - `go.mod` (`module github.com/mlorentedev/kubelab/widget-proxy`, Go 1.25 matching `apps/api`)
  - `cmd/widget-proxy/main.go` (HTTP server on `:8080`, graceful shutdown, structured logging via `log/slog`)
  - `internal/health/check.go` — `Check(ctx, target Target) Result` doing one HTTP GET with 5 s timeout; classifies status: 2xx = `up`, 3xx/4xx (except documented auth codes) = `degraded`, 5xx / timeout / refused = `down`. Returns `{status, code, latency_ms}`.
  - `internal/targets/loader.go` — reads `/etc/widget-proxy/targets.yaml` at startup, supports `SIGHUP` reload (cheap; pod restart on ConfigMap change is also fine).
- [ ] Unit tests with `httptest.NewServer` for each branch (up / degraded / down / timeout).
- [ ] `make -C apps/widget-proxy test` exits 0.

## T2 — Toolkit generator for target ConfigMap (~50 LOC)

- [ ] `toolkit/scripts/sync_widget_proxy_targets.py` — sibling of `sync_homepage_config.py`. Reads `infra/config/values/common.yaml`, walks `apps.services.*`, emits ConfigMap YAML to `infra/k8s/base/services/widget-proxy-targets.yaml` with one entry per target: `{ name, url, expect_status: <int|null>, auth_protected: <bool> }`.
- [ ] Wired into `toolkit/cli/sync.py` as a sub-command (`toolkit sync widget-proxy-targets`) and Makefile target `sync-widget-proxy-targets`.
- [ ] `make test` covers the generator (1 happy-path test with fixture common.yaml fragment).
- [ ] Regenerated ConfigMap is byte-stable across runs (no timestamps / random ordering).

## T3 — K3s manifests (~80 LOC)

- [ ] `infra/k8s/base/services/widget-proxy.yaml` — Deployment (1 replica, resource limits 50m CPU / 64Mi mem, scratch image), Service (ClusterIP, port 8080), IngressRoute (host `widgets.staging.kubelab.live`, `certResolver: letsencrypt`, middlewares `crowdsec-bouncer` + a new `widget-proxy-ratelimit`), Middleware (rate limit average 50 rps, burst 100, per IP).
- [ ] ConfigMap mount: target list from T2 → `/etc/widget-proxy/targets.yaml`.
- [ ] Add the service to `infra/k8s/base/kustomization.yaml` `resources:` list.
- [ ] Generated `widget-proxy-targets.yaml` (T2 output) is committed; deploy script regenerates and diffs it before apply (no drift).
- [ ] Prod overlay decision deferred to a follow-up — staging-only for v1 (proxy lives next to its cockpit consumer; prod adds the same manifests once smoke is green).

## T4 — Homepage cockpit migration to `customapi` (~30 LOC)

- [ ] `infra/k8s/base/services/homepage-templates/services.yaml.j2` — migrate at least three representative tiles from `ping:` to `widget: { type: customapi, url: https://widgets.staging.kubelab.live/health?target=<name>, mappings: [...] }`. Suggested: Grafana, Gitea, n8n (services currently rendered with a misleading "up").
- [ ] `make sync-homepage` regenerates `services.yaml`; diff shows only the migrated tiles + Cloudflare auto-bump.
- [ ] No regression in other widgets (Glances tiles unaffected).

## T5 — Verification (live smoke + incident drill)

- [ ] `make deploy-k8s ENV=staging` rolls out `widget-proxy` Deployment cleanly. `kubectl get pods -n kubelab -l app=widget-proxy` shows `Running 1/1`.
- [ ] `curl -s https://widgets.staging.kubelab.live/health?target=grafana | jq .` returns the expected JSON, real status code visible.
- [ ] Browser check on `home.staging.kubelab.live`: the three migrated tiles render real colors (green / red as their backend dictates).
- [ ] **Incident drill**: `kubectl scale -n kubelab deploy/grafana --replicas=0`; cockpit tile turns red within the refresh window; scale back to 1; tile turns green. Capture screenshot or log line as evidence in `verification.md`.
- [ ] Rate-limit verification: `hey -n 1000 -c 100 https://widgets.staging.kubelab.live/health?target=grafana` — 200s under the configured threshold, 429s above. Document numbers.

## Closing

- [ ] Every AC from `proposal.md` (AC1–AC7) covered by at least one task above.
- [ ] `make test` 91+ passing.
- [ ] `make lint` clean (Go vet + ruff + yamllint + ansible-lint).
- [ ] No unrelated changes (audit `git diff master --stat` before push).
- [ ] `verification.md` filled with evidence (HTTP captures, drill logs, rate-limit numbers).
- [ ] PR opened referencing this spec folder.
- [ ] Beelink / aws1 status unchanged (this PR does not touch their tiles).

## Machine-readable features

Spec emits a sibling `features.json`. Each AC maps to ≥1 feature; the harness verifies and sets `state: passing`.

```json
[
  {
    "id": "DT-004-widget-proxy-f1",
    "behavior": "widget-proxy Deployment healthy in kubelab namespace",
    "verification": "kubectl get pod -n kubelab -l app=widget-proxy -o json | jq -e '.items[0].status.containerStatuses[0].ready'",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f2",
    "behavior": "/health?target=<svc> returns JSON with real status code matching K8s reality",
    "verification": "curl -sf https://widgets.staging.kubelab.live/health?target=grafana | jq -e '.status == \"up\" and (.code | tostring | startswith(\"2\"))'",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f3",
    "behavior": "Homepage cockpit renders 3+ tiles via customapi widget with real colors",
    "verification": "grep -c 'type: customapi' infra/k8s/base/services/homepage-config/services.yaml | awk '$1 >= 3 {exit 0} {exit 1}'",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f4",
    "behavior": "Generated ConfigMap is byte-stable across consecutive sync runs",
    "verification": "make sync-widget-proxy-targets && cp infra/k8s/base/services/widget-proxy-targets.yaml /tmp/a.yaml && make sync-widget-proxy-targets && diff -q infra/k8s/base/services/widget-proxy-targets.yaml /tmp/a.yaml",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f5",
    "behavior": "Incident drill: scaling target to 0 flips tile red within refresh window",
    "verification": "manual / scripted via kubectl + curl; evidence in verification.md (screenshot or log capture).",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f6",
    "behavior": "IngressRoute serves valid Let's Encrypt cert chain",
    "verification": "curl -vI https://widgets.staging.kubelab.live/health 2>&1 | grep -q \"issuer.*Let's Encrypt\"",
    "state": "pending",
    "evidence": ""
  },
  {
    "id": "DT-004-widget-proxy-f7",
    "behavior": "Rate limiting middleware returns 429 above threshold",
    "verification": "hey -n 1000 -c 100 https://widgets.staging.kubelab.live/health?target=grafana | grep -q '429'",
    "state": "pending",
    "evidence": ""
  }
]
```
