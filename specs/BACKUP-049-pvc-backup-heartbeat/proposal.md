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

- **Which endpoint the pod posts to** is not settled by reading manifests. The
  in-cluster `uptime-kuma` Service (kubelab namespace, EndpointSlice to
  `100.64.0.6:3001`) avoids a public round trip and the CrowdSec and rate-limit
  middlewares; the public host is the fallback. Decide by measuring from inside
  the cluster — this is the one question implementation must answer by probing.
- **`muted_notification_tags` could silence this monitor.** That set exists so
  on-demand homelab targets do not alert when the homelab is off (#912). A
  heartbeat monitor that inherits a muted tag is a control that cannot fire — the
  exact failure class this spec exists to remove, reintroduced by a tag. AC6
  asserts against the live notification links rather than the seed for that
  reason.
- **The scratch monitor of AC3 must be removed afterwards.** The sync is
  declarative and deletes what the seed does not declare, so an unremoved scratch
  entry is either deleted on the next apply (fine) or, if someone adds it to the
  seed to stop that, becomes a permanent monitor nobody watches.

## Decisions

Taken 2026-08-19, with the reasoning, so the archived record says why and not
only what.

- **The demonstration is staged, and prod's CronJob is never stopped.** AC9's
  standard is "stop the thing and observe the alert". The obvious stop —
  `kubectl patch cronjob pvc-backup -p '{"spec":{"suspend":true}}'` — is a manual
  write to `spec.suspend`, a field no manifest declares, on the exact object
  whose ownership incident produced this spec. Under SSA that annexes the field
  to a foreign manager, re-creating the defect measured in lesson 351 on the
  object cleaned five days earlier, and prod runs `selfHeal: true` besides. At a
  ~26h interval it would also be a multi-day demo.
  So the proof is composed of two halves that each run in minutes: a **scratch
  push monitor** at a 60s interval, carrying the real notification links, is
  stopped by simply not posting to it — proving Kuma-to-operator end to end
  through the real channel; and the **first real heartbeat** from a live backup
  run proves CronJob-to-Kuma. Neither half touches prod's CronJob.
  Accepted cost, stated plainly: no single execution traverses the whole chain.
  The seam is the notification config, and AC6 pins that the real monitor carries
  the same links the scratch one proved.
- **A heartbeat that cannot be delivered does not fail the backup.** The backup
  has already completed by then; failing the job would trip `backoffLimit` and
  re-run a finished backup, and would make Uptime Kuma an availability dependency
  of the backup itself. Nothing is lost by not failing: an undelivered heartbeat
  is an *absent* heartbeat, so Kuma alerts one window later regardless. **The
  control detects its own delivery failure** — which is the property that makes
  this the safe direction rather than the lazy one.
- **`curl` joins the existing `apk add` line.** This does extend the
  runtime-install pattern the incident criticised, and that is accepted rather
  than hidden: it is the same line that already installs `sqlite`, so it adds no
  new failure class, and it buys the hardening proven in
  `roles/node_maintenance/templates/kubelab-maintenance-notify.sh.j2` — the token
  passed via `--config -` instead of `argv`, bounded timeouts, and a `--retry`
  budget that fits inside `activeDeadlineSeconds`. Busybox `wget` would avoid the
  install but cannot read a config from stdin, and the token is *in the URL* for
  a push endpoint, so it would sit in `argv` and be readable from the node's
  `/proc`.
- **The monitor's key is `prod-backup-pvc-heartbeat`**, SOPS sub-key
  `push_tokens.prod_backup_pvc_heartbeat`. `prod` is an existing domain prefix in
  the seed (`prod-api-api-kubelab-live`, `prod-web-kubelab-live`); `ops` is not,
  in the 31 keys or in `tags.json`. The `_` spelling in SOPS is required so the
  path survives `_flatten_dict` into an env var name — see #1169.

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
- [ ] The **absence** of heartbeats raises an alert that reaches the operator's
      real notification channel, without anyone looking. Demonstrated on a
      scratch push monitor at a short interval, carrying the same notification
      links as the real one and stopped by not posting to it — observed
      arriving, not inferred from configuration (BACKUP-044 AC9's standard).
- [ ] **No step of the demonstration adds a field manager to the prod CronJob**,
      verified with `--show-managed-fields` before and after. A demo that
      re-creates the ownership defect this spec descends from is not a passing
      demo.
- [ ] The push token is absent from every committed file, and the seed survives
      an `export` -> `apply` round trip with the live token unchanged.
- [ ] The heartbeat monitor is not silenced by `muted_notification_tags`, asserted
      against the live monitor's notification links rather than against the seed.
- [ ] A heartbeat that cannot be delivered leaves the backup's exit status
      **unchanged**, tested by pointing the sender at an unreachable endpoint
      rather than by reading the `|| true`.
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
