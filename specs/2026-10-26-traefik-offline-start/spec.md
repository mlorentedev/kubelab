---
id: 2026-10-26-traefik-offline-start
type: spec
status: active
created: "2026-10-26"
owner: manu
issue: "kubelab#2565"
---
# Traefik starts and renews without depending on the site's network

## Intent

Two failures of the same shape, both measured on staging after the lab moved site (NET-005).

1. **Plugins (#2565).** Traefik downloads its plugins (`bouncer`, `api-key`) from `plugins.traefik.io` at every start. When the download fails, Traefik starts with every plugin disabled and drops each router that uses one. The pod stays Ready and Argo CD reports Synced/Healthy. ace1 booted without egress, K3s started the moment the edge served a default route (2026-10-27 00:51:47Z), and Traefik tried the download 17 s later. Every CrowdSec-protected staging route answered 404 until a manual restart. Prod has the same dependency.
2. **ACME (#2699).** lego checks the DNS-01 TXT record against the zone's authoritative nameservers over UDP 53 before it asks Let's Encrypt to validate. The current site answers every outbound UDP 53 query itself, so the check sees a cached NXDOMAIN and every staging renewal times out. Staging certificates expire 2026-11-25.

## Scope

- The `k3s_server` role fetches each plugin's source at a pinned tag, verified by sha256, into one directory per version on the node (`k3s_traefik_local_plugins`, `k3s_traefik_local_plugins_dir`), and prunes versions no longer declared. Traefik loads them as `experimental.localPlugins` (`type: hostPath`); `experimental.plugins` goes away, so a start downloads nothing.
- `experimental.abortOnPluginFailure: true`: a plugin that does not load stops Traefik instead of starting it without its routes. The chart's rolling update (`maxUnavailable: 0`) keeps the old pod serving while a new one fails.
- Both plugins stay, per the operator's decision on #2565 (ADR-035 Stage 1 reserves `api-key`).
- ACME: `dnschallenge.propagation.disableChecks=true` and `delayBeforeChecks=60s` in both environments, behind `k3s_traefik_acme_propagation_checks` (operator decision 2026-10-26: both environments, so staging and prod do not drift).

Out of scope: the Loki alert on `Plugins are disabled` / `invalid middleware ... does not exist` (it lands in `infra/k8s/**`, owner-merged; with local plugins and abort-on-failure the silent state no longer exists, so the alert would guard a state the design removed), and the lab's resolver trust path (CoreDNS forwarding over TLS), which belongs to the NET-005 site-acceptance plan.

## Checklist

- [x] Role defaults declare both plugins with module, version and sha256, the plugin directory, and the ACME toggle.
- [x] Tasks fetch, verify, unpack and prune, idempotently, before the HelmChartConfig is templated.
- [x] The HelmChartConfig renders `localPlugins` (hostPath) and `abortOnPluginFailure`, and no `experimental.plugins`.
- [x] Tests: rendered config, every plugin a Middleware uses is declared locally, pins are well-formed, tasks order, ACME flags.
- [x] Lessons 625 (plugins) and 626 (DNS interception).
- [x] Staging: `make provision NODE=ace1 ENV=staging TAGS=k3s`, re-run `changed=0`, Traefik logs no plugin download and no plugin error, CrowdSec-protected routes answer, renewals succeed.
- [ ] Prod: `make provision NODE=vps ENV=prod TAGS=k3s` after merge, same checks, `make test-e2e ENV=prod`.

## Evidence

Staging, 2026-10-27 UTC (ace1, from this branch):

- `make provision NODE=ace1 ENV=staging TAGS=k3s`: `ok=37 changed=4 failed=0` (directories, download, unpack, HelmChartConfig). Re-run: `ok=36 changed=0 failed=0` (the unpack skips on its `creates`).
- Traefik's new pod logged `Loading plugins...` and `Plugins loaded. plugins=["api-key","bouncer"]` in the same second (03:02:27Z). The remote download took 17 s at the 00:51 boot. No `Plugins are disabled` and no `middleware ... does not exist` since.
- CrowdSec-protected routes answer: n8n 200, status 302, traefik 302, pihole `/admin/` 302, grafana 302, auth 200. No 404.
- ACME: the renewals that had failed since the site move with `propagation: time limit exceeded: last error: authoritative nameserver ... NXDOMAIN` succeed one after another at about 70 s each (60 s delay plus validation). Served certificates moved from `notAfter=Nov 25 2026` to `notAfter=Jan 25 2027` for staging.mlorente.dev, n8n and console.minio within minutes of the restart.

## Next

Merge, then `make provision NODE=vps ENV=prod TAGS=k3s`, the same checks on prod, and `make test-e2e ENV=prod`.

## Promotion candidates

- [x] Lesson? `yes`: 625 and 626.
- [x] ADR? `amendment`: ADR-035 gains a one-line note that its `api-key` plugin is now loaded from the node; the decision itself is recorded on #2565.
- [ ] Pattern? `no`
