---
id: "BACKUP-049-pvc-backup-heartbeat"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-19"
issue: "mlorentedev/kubelab#1171"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-049-pvc-backup-heartbeat

## Why

The prod PVC backup ran for the last time on 2026-08-14 and nobody found out until
2026-08-19, when someone ran `kubectl get jobs` for an unrelated reason. Four
consecutive failures, no notification of any kind: `overlays/prod/backup.yaml`
carries `failedJobsHistoryLimit: 3`, which retains evidence for whoever goes
looking and tells nobody. Every control this repository has around backups
asserts something about the runs that *exist*; none of them can see a run that
never happened, which is the shape this failure took and the shape BACKUP-044's
AC9 names.

## What

The backup posts a heartbeat on success, and something outside its own failure
domain alerts when the heartbeat stops arriving.

Concretely: a `push` monitor on the RPi3's Uptime Kuma, whose interval is longer
than the CronJob's daily period by an agreed grace margin. The CronJob's script
posts to it as its final step, after every backup has completed, so `set -e`
guarantees a failed run never reaches it. When no heartbeat arrives inside the
window, Kuma marks the monitor DOWN and the existing default notification fires.

The watcher is deliberately not in the thing being watched. Uptime Kuma is
already the monitoring of record (ADR-028) and runs on the RPi3 — a different
host, site and power domain from the Hetzner VPS that runs prod. A watcher inside
prod would go dark with the thing it watches.

This covers all three failure shapes with one mechanism, which is the point:

| Failure | Cluster reports | Heartbeat |
|---|---|---|
| Pod never scheduled (the real 2026-08-14 cause: a missing PVC) | `Pending` -> `DeadlineExceeded` | absent |
| Job hangs (`mc` downloaded from the internet inside the backup path) | `DeadlineExceeded` | absent |
| CronJob suspended, deleted, or scheduling silently stopped | **nothing at all** | absent |

The third has no object to inspect. It is the reason a heartbeat is the right
primitive rather than a better inspection of Job status.

## Out of scope

- **The notification fabric's own watchdog** (#1021). Identical mechanism,
  different subject — that ticket asks who watches n8n and Apprise. This one
  assumes the fabric works; if it does not, #1021 is the control that says so.
- **PVC backup *coverage*** (#1111 / BACKUP-046). Five of five ratified claims
  are uncovered. This spec makes the *existing* job's silence audible; it does
  not widen what the job backs up.
- **The unpinned `mc` download inside the backup path.** A real defect, named in
  the incident, and a dependency on the public internet inside a backup. It is
  not this spec's, and fixing it here would mean this change could not be
  reverted independently.
- **The field-manager residue sweep** (#1164). Its disposition is decided and
  separately tracked. It constrains *how* this spec runs its demo (below) but is
  not part of the deliverable.
- **Anything restic or R2.** BACKUP-044's node-path class is a different pipeline.

## Risks / open questions

- **The demonstration is the hard part, and the obvious method is forbidden.**
  AC9's standard is "stop the thing and observe the alert, not read the query".
  The obvious stop is `kubectl patch cronjob pvc-backup -p '{"spec":{"suspend":true}}'`
  — a manual write to `spec.suspend`, a field no manifest declares, on the exact
  object that was the poster child of the ownership incident. Under SSA that
  annexes the field to a foreign manager permanently, re-creating the defect
  measured in lesson 351 on the object cleaned five days earlier, and prod's
  `selfHeal: true` races any out-of-band toggle besides. **The stop mechanism must
  be chosen and justified before implementation.** Compounding it: at a ~26h
  interval, "stop and wait" is a multi-day demo unless it is staged.
- **What a failed heartbeat should do to a successful backup.** Failing the job on
  a delivery error makes Uptime Kuma an availability dependency of the backup and
  re-runs a backup that already completed. Not failing it is defensible precisely
  because an absent heartbeat *is* the alert — the control catches its own
  delivery failure one window later. Either is defensible; silence is not.
- **`alpine:3.21` has no `curl`.** The hardening being reused is curl-specific
  (`--config -` to keep the token out of `argv`, `--retry-max-time` budgets).
  Adding `curl` to the existing `apk add` line extends the runtime-install
  pattern the incident criticised, on the same line that already installs
  `sqlite`. Busybox `wget` avoids the install and cannot read a config from
  stdin, so the token would sit in `argv`. Trade-off, to be stated not dodged.
- **Which endpoint the pod posts to** is not settled by reading manifests. The
  in-cluster `uptime-kuma` Service (kubelab namespace, EndpointSlice to
  `100.64.0.6:3001`) avoids a public round trip and the CrowdSec and rate-limit
  middlewares; the public host is the fallback. Decide by measuring from inside
  the cluster.
- **`muted_notification_tags` could silence this monitor.** That set exists so
  on-demand homelab targets do not alert when the homelab is off (#912). A
  heartbeat monitor that inherits a muted tag is a control that cannot fire — the
  exact failure class this spec exists to remove, reintroduced by a tag.
- **The monitor's `key` is load-bearing, not cosmetic**: it is also the SOPS
  sub-key that resolves the token.

### Settled by measurement

- **Kuma accepts the interval.** Probed against the pinned image in a throwaway
  container, 2026-08-19: `3600`, `86400`, `90000`, `93600`, `172800` and `604800`
  are all accepted and stored verbatim. A ~26h window is not near a limit, so the
  grace margin can live in `interval` itself rather than being smuggled into
  `retries`.
- **An explicitly-set `pushToken` is stored verbatim** by the same raw-socket
  create path the toolkit uses. Independent confirmation of #1169's fix.
- **The toolkit could not manage a push monitor at all** — token dropped on
  export, never set on create, never repaired when rotated. Fixed in #1169
  (PR #1170), which must land before anything here can be declared in the SSOT.

## Acceptance criteria

- [ ] A successful backup posts exactly one heartbeat and the monitor reads UP,
      demonstrated by a real run rather than by reading the script.
- [ ] A backup that fails at any step posts **no** heartbeat, demonstrated by
      injecting a failure — not by arguing from `set -e`.
- [ ] A backup that never starts raises an alert that reaches the operator's real
      notification channel, without anyone looking. Demonstrated by stopping the
      job and observing the alert (BACKUP-044 AC9's standard).
- [ ] The stop used above leaves **no new field manager** on the CronJob,
      verified with `--show-managed-fields` before and after. A demo that
      re-creates the ownership defect is not a passing demo.
- [ ] The push token is absent from every committed file, and the seed survives
      an `export` -> `apply` round trip with the live token unchanged.
- [ ] The heartbeat monitor is not silenced by `muted_notification_tags`, asserted
      against the live monitor's notification links rather than against the seed.
- [ ] A heartbeat that cannot be delivered has a stated, tested effect on the
      backup's own exit status.
- [ ] The token is registered in `SECRET_CATALOG` and appears in
      `make secrets-audit --env prod`. Checked against the ANSIBLE-033 failure
      mode: an `envs` tuple matching no real env removes a secret from every
      audit, silently.

> The order of this list is load-bearing: `tasks.md` and `verification.md` refer
> to these criteria positionally, as `[AC1]`..`[AC8]`. Append new criteria.
> Inserting one renumbers every marker below it, silently and everywhere.

## References

- Bitácora board: **kubelab#1171** (see the `issue:` frontmatter field)
- **kubelab#1169** / PR #1170 — the toolkit substrate; this cannot be declared in
  the SSOT until it lands.
- **kubelab#1163** — the incident. **kubelab#1164** — its root cause, and the
  constraint on this spec's demo.
- **kubelab#1021** — the same mechanism for the notification fabric.
- **kubelab#1111** — PVC backup coverage. **kubelab#1056** — BACKUP-044, whose
  AC9 is this spec's standard of proof.
- [ADR-024](../../docs/adr/adr-024-pvc-backup-strategy.md),
  [ADR-028](../../docs/adr/adr-028-operational-topology.md)
- `docs/lessons/kubernetes/lesson-351-a-manual-kubectl-apply-annexes-the-fields-it-touches.md`
