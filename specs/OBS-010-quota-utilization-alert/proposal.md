---
id: "OBS-010-quota-utilization-alert"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-08-14"
issue: "kubelab#918"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# OBS-010: Quota utilization alert

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #918: OBS-010: alert on namespace quota utilization, so the early signal is not a blocked deploy -->

The `kubelab` `ResourceQuota` (#811, live in prod since 2026-08-14) can only admit or reject at the moment a pod is scheduled — it has no concept of "getting close." The first signal anyone gets that the namespace is running out of room is a failed deploy, at the worst possible time to discover it.

The tempting fix — tightening the quota, or making staging stricter than prod, to catch growth earlier — converts every early warning into a blocked deploy. The predictable end state is the ceiling gets raised to unblock work until it stops constraining anything, the same dynamic #912 already names as a failure mode elsewhere in this estate. Detection and enforcement need to be different mechanisms: the quota enforces, and this spec adds the thing that watches it from a comfortable distance.

## What

A Grafana alert fires when either dimension of the `kubelab` `ResourceQuota` (`requests.memory`, `limits.memory`) crosses 80% of its hard ceiling and stays there for 5 minutes, delivered through the Apprise/Loki fabric #799 (OBS-007) already built — prod pages, staging archives, same tiers, same contact points, no new delivery path.

Three observable changes:

1. A new CronJob (`quota-watcher`, every 5 minutes) reads the live `ResourceQuota` via the in-cluster API and emits one structured log line per dimension (`used`, `hard`, `pct`) to stdout, picked up by the existing Vector → Loki pipeline like every other container's logs.
2. Two Grafana alert rules (`quota-utilization-requests`, `quota-utilization-limits`) watch those log lines. Crossing 80% and staying there for 5 minutes fires; dropping back below does not (and correctly resolves — silence from the alert is not silence from the rule, it just means it isn't breached).
3. If the emitter itself stops producing log lines — CronJob failing, RBAC broken, API unreachable — the alert fires instead of going quiet. Absence of data is itself a signal here, the opposite of OBS-007's cert-expiry rule.

## Out of scope

- **A metrics pipeline (Prometheus, kube-state-metrics).** This repo's observability stack is deliberately Loki-only (ADR-028) — verified 2026-08-14, no Prometheus datasource or kube-state-metrics deployment exists anywhere in `infra/k8s`. Standing one up is a platform decision with its own storage/retention/cost tradeoffs, not something a single alerting ticket should trigger. The log-line emitter below reuses the fabric that already exists.
- **CPU utilization alerting.** IDP-031 explicitly did not put a `ResourceQuota` on any CPU dimension (compressible, throttles rather than kills) — there is nothing for this spec to alert on for CPU.
- **`kube-system`'s LimitRange (#924/OBS-009).** That spec deliberately has no `ResourceQuota` (a system namespace can't safely reject at admission) — there is no utilization number to alert on there, by design.
- **Tightening the quota itself, in either environment.** That is exactly the anti-pattern this spec exists to avoid — see Why.
- **#799's own cert-expiry rule.** Reuses its delivery path, not its content. No changes to `rules.yaml`'s existing `certificates` group.

## Risks / open questions

- **`noDataState` must be `Alerting`, the inverse of OBS-007's `ACME certificate failure` rule.** For that rule, no matching log lines means certificates are fine (`noDataState: OK`). Here, no matching log lines means the emitter is broken and the quota could be at 100% with nobody told — `noDataState: OK` here would silently disarm the alert exactly when a real problem also breaks the emitter (e.g. the API server itself under pressure). Mitigation: set `noDataState: Alerting` on both rules, and cover it with an explicit acceptance criterion so a future copy-paste from OBS-007's rule doesn't inherit the wrong default.
- **A routine surge must not fire this alert.** IDP-031's own measured surge case (full `make deploy-k8s` + rollout restart of all 14 deployments, 2026-08-12) peaked at `limits.memory` 6272Mi/7168Mi = **87.5%** — comfortably over the proposed 80% threshold, during entirely normal operation. Mitigation is `for: 5m` against a CronJob sampling every 5 minutes (mirroring OBS-007's own `interval: 5m` / 10-minute LogQL window). **This mitigation was incomplete as originally reasoned, and the gap was real, not theoretical**: the first implementation used `max_over_time([10m])`, which returns the peak seen ANYWHERE in the window — so a single transient spike stayed visible to every evaluation for up to 10 minutes after it happened, regardless of the current value, defeating `for: 5m` entirely. Reproducing the surge drill in staging fired the alert for real. Fixed with `last_over_time` (reflects only the most recent sample, so `for:` now genuinely requires two real elevated readings five minutes apart), re-verified clean, locked in with a regression test. See `verification.md` for the full incident.
- **The emitter needs read access to a namespace-scoped API object it doesn't otherwise touch.** A new ServiceAccount + Role (`get` on `resourcequotas` in `kubelab` only, nothing else) + RoleBinding. Because these ship through the namespaced Kustomize overlay, `make deploy-k8s`'s impersonation (TOOL-029) means `spoke-rbac.yaml`'s write role must cover `serviceaccounts`/`roles`/`rolebindings`/`cronjobs` in `kubelab` *before* the deploy — check with `kubectl auth can-i --as=system:serviceaccount:kubelab:argocd-manager`, not after a `forbidden` (the #948 pattern IDP-031 already hit once).
- **`automountServiceAccountToken` must stay `true` on this one CronJob, against the fleet's own norm.** CLAUDE.md's Authelia/n8n gotchas both say to disable it. Here the token is the only way the container authenticates to the API server — disabling it would silently break the emitter in a way that produces no log lines, which is exactly the failure mode point 1 above is designed to catch. Comment the manifest so a future "harden this like everything else" pass doesn't flip it.
- **Unit conversion in the emitter.** `ResourceQuota.status.{hard,used}` reports memory as Kubernetes quantity strings (`"4Gi"`, `"2400Mi"`), not raw numbers — the shell script must normalize both to the same unit before dividing. Getting this wrong produces a percentage that is silently off by a power of 2, not an error. Verified against real prod values in Part 1's test before trusting the emitter's arithmetic.

## Acceptance criteria

- [x] The `quota-watcher` CronJob runs every 5 minutes in `kubelab`, reads the live `ResourceQuota` via the in-cluster API (its own ServiceAccount, scoped to `get resourcequotas` only), and its pods' logs contain one structured JSON line per dimension with correct `used`/`hard`/`pct` values — verified against `kubectl get resourcequota -o json`'s own numbers, not re-derived from the emitter's own math.
- [x] Two Grafana alert rules (`quota-utilization-requests`, `quota-utilization-limits`) are provisioned from git (verified via the provisioning API, per OBS-007's own test pattern), route through the existing Apprise contact points, `for: 5m`, `noDataState: Alerting`.
- [x] Reproducing IDP-031's surge drill (full `make deploy-k8s ENV=staging` + rollout restart of all deployments) in staging does **not** fire either rule, despite `limits.memory` crossing 80% during the restart — exercised, not assumed. First attempt failed for real (see Risks above); fixed and re-verified clean.
- [x] Killing the emitter (scale the CronJob's schedule suspend, or delete its RBAC) causes both rules to move to `Alerting` within one `for:` window, proving `noDataState: Alerting` actually works rather than just being set.

## References

- Bitácora board: **kubelab#918** (see the `issue:` frontmatter field)
- **kubelab#811 (IDP-031)** — the ResourceQuota this spec alerts on. Live in prod, verified 2026-08-14 (see IDP-031 verification.md).
- **kubelab#799 (OBS-007)** — the alerting delivery path (Grafana contact points, notification policies, Apprise tiers) this spec reuses rather than rebuilds.
