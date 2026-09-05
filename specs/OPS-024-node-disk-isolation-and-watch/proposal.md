---
id: "OPS-024-node-disk-isolation-and-watch"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-04"
issue: "mlorentedev/kubelab#1657"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# OPS-024-node-disk-isolation-and-watch

## Why

<!-- from issue #1657: OPS-024: the Beelink root filesystem is full and the forge is down for writes -->

On 2026-09-05 the Beelink's root filesystem reached 100% with 0 bytes free, and
Gitea's SQLite could not write: **the forge went down for writes** — no pushes,
no pull requests, no issues — while act_runner spun on `pick task: database or
disk is full`. That was two failures, not one, and only the second is an outage:
CI accumulated storage without bound, **and** that took the forge down, because
25GB of CI cache and 59MB of Gitea data share one ext4 filesystem. This spec is
about the second.

The first failure already has an answer in flight (#1665's `make node-reclaim`,
merged or open; AC2 below wires it into the timer). The second has none, and it
is the one that decides whether the next accumulation is an inconvenience or an
outage.

## What

Three observable changes, in decreasing order of how much they guarantee:

1. **`/var/lib/docker` sits on its own LVM logical volume**, declared in Ansible
   and idempotent. CI filling its cache then exhausts CI's volume and leaves the
   root filesystem — and therefore Gitea's database — writable. The 235GB volume
   group currently has **135.42GB unallocated** and the root LV is 100GB, so the
   space exists today.
2. **Non-K8s nodes report root-filesystem usage into the existing alert.**
   `obs015-disk-root-saturation` already evaluates `disk_root_usage` from Loki
   and works; it is fed only by the `disk-watcher` CronJob, which runs in K3s.
   The Beelink, RPi3, RPi4, ace2 and the Jetson are not in K3s and have
   therefore never been watched by it.
3. **`node_maintenance` reaps orphaned buildx builders** instead of only
   reporting them, using the `Created`-based age gate #1665 introduced.

## Out of scope

- **Stopping CI from producing the residue.** `personal/resume#262` removes
  `docker/setup-buildx-action`, and the `SCHEME=full` base image is #1657 AC5.
  Both are changes in another repository.
- **`builder.gc` / `keepStorage` in `daemon.json`.** Measured before the
  reclaim, `docker system df` reported **Build Cache: 844.3MB** against 18.9GB
  of orphaned state volumes and ~40GB of images. It bounds 0.8% of the problem,
  and `docker builder prune -af` already runs weekly. Worth doing eventually,
  not part of this.
- **Migrating the Beelink into K3s** to inherit `disk-watcher`. ADR-028 places
  it deliberately outside; that decision is not reopened here.
- **A second alerting brain.** See the first risk below.

## Risks / open questions

- **The LV migration is a one-shot path against production with no rehearsal
  target.** `/var/lib/docker` holds ~25GB of *live* state, so the role needs a
  first-run sequence (stop Docker → rsync → mount → start) that is *not* its
  steady-state converge. ace2, the only comparable Docker host, is powered off.
  The role must therefore be safe to interrupt, and the migration must be
  verifiable before Docker is restarted rather than after.
- **Isolation is not absolute, and the residual is unmeasured.** Gitea's *data*
  is a bind mount at `/opt/gitea` (59MB) and is genuinely protected, but its
  *container* writable layer and logs live under `/var/lib/docker`, on the
  isolated LV. Whether a full LV degrades or kills the running Gitea container
  is **not established**. It must be tested with a deliberately small LV before
  anyone claims the failure mode moved; if it does not hold, the answer is a
  reserve within the LV, not a louder claim.
- **An alert is detection, not assurance.** CLAUDE.md already records
  2026-08-24: Uptime Kuma detected an outage in 4 minutes and it went unread for
  35. AC2 must not be described as preventing recurrence.
- **Two independent disk rules would be a regression, not redundancy.** The
  repo's ratified pattern is lesson-285 — *converge the brain, specialize the
  egress* — already implemented as one n8n ingress with Apprise egress
  (`apprise-page` / `apprise-log`). Node producers therefore feed the
  **existing** rule; `node_notify` keeps its actual job (`OnFailure=` for unit
  failures) and does not become a second disk evaluator. Two rules drift, and
  one stops evaluating silently, which is the failure class this incident
  belongs to.
- **`noDataState: OK` means "watched" cannot mean "we would know if it stopped
  reporting".** Found by adversarial review, and verified: `disk-rules.yaml:18`
  gives `obs015-pvc-unbound-failure` `noDataState: Alerting`, with a comment
  explaining that a metric which must never go quiet needs it — while
  `disk-rules.yaml:102` gives `obs015-disk-root-saturation` `noDataState: OK`.
  A dead producer therefore reads as healthy.

  **This is not flipped to `Alerting`, and the reason is ADR-028.** The nodes
  this spec adds are the *on-demand* half of the fleet: the Beelink, RPi4, ace2
  and the Jetson are off most of the time by design, so `Alerting` on no-data
  would page continuously for the intended state. The honest consequence, which
  the spec records rather than engineers around: **for an on-demand node this
  alert protects it only while it is running** — which is also the only time its
  disk fills, since nothing writes to a powered-off node. What must not happen
  is an *always-on* node inheriting that silence, so AC8 draws the line where
  ADR-028 already draws it.
- **The producer must land in the stream the rule already selects.** The rule
  selects `{container="disk-watcher"}` and groups `by (node)`. A producer that
  labels its stream anything else is never evaluated and AC4 passes vacuously.
- **#1665 is not on `master`.** Verified: `git cat-file -e
  origin/master:toolkit/features/docker_reclaim.py` fails. PR-D cannot reuse the
  planner until #1665 lands, so PR-D is sequenced last and blocked on it.

**Resolved by adversarial review** (`review.md`, `nan/deepseek-v4-flash`):

- *Direct Loki push vs a shipper* → **direct push**, as the smaller change,
  subject to the stream-label constraint above.
- *Does `by (node)` survive a node label* → **yes**. The CronJob emits no `node`
  label and groups under an empty one; a producer that emits `node` groups
  per-node. Distinct and correct; `disk-rules.yaml` already states the identity
  choice ("node, not `pod`", OBS-018 AC5).

## Acceptance criteria

- [ ] **AC1** An Ansible role declares the Beelink's `/var/lib/docker` on its own
      LV, sized from the SSOT and not hardcoded. Re-run reports `changed=0`.
- [ ] **AC2** Isolation is proven on a **sacrificial LV, never on production's**.
      A small LV is mounted at `/var/lib/docker` on a rehearsal host, filled with
      `fallocate`, and Gitea — running against it — still accepts a **real
      write** (an issue created, a push landed), not a health check: the
      container reported `healthy` throughout the original incident.
      Filling production's `/var/lib/docker` is explicitly forbidden as the AC's
      method — Gitea's writable layer and logs live on that LV, so the test
      would risk reproducing the outage it exists to prevent. If the sacrificial
      run shows Gitea degrading, the residual is recorded and a reserve added
      inside the LV; the AC is not quietly reworded to match what happened.
- [ ] **AC3** The migration path is proven interruptible: killed midway, Docker
      restarts against intact data. Rehearsed somewhere other than the Beelink.
- [ ] **AC4** A non-K8s node's root-filesystem usage reaches
      `obs015-disk-root-saturation`, and `make alerts` shows it firing when the
      node crosses 90% — verified by consequence on a real threshold crossing,
      not by asserting the log line was emitted.
- [ ] **AC5** The alert covers every node declared in `networking.nodes`, not
      only the Beelink. A node added to the SSOT without a watcher fails a test.
- [ ] **AC6** `node_maintenance` removes age-gated orphaned builders rather than
      only reporting them, reusing #1665's planner. Re-run reports `changed=0`.
- [ ] **AC7** #1456 is closed or updated: its report-only posture is superseded
      by AC6, and the reason it chose reporting (no trustworthy age signal) no
      longer holds.
- [ ] **AC8** The producer emits into `{container="disk-watcher"}` with a `node`
      label, and a committed test asserts that an **always-on** node
      (ADR-028: VPS, aws1/gcp1, RPi3) is never left relying on
      `noDataState: OK` — an always-on node that stops reporting must alert.
      On-demand nodes are exempt by declaration, named individually, so adding a
      node to `networking.nodes` forces the choice rather than inheriting
      silence.

## References

- Bitácora board: `mlorentedev/kubelab#1657` (see the `issue:` frontmatter field)
- `mlorentedev/kubelab#1456` — ANSIBLE-046, which measured these same builders on
  2026-08-27 and scoped their cost to RAM
- `mlorentedev/kubelab#1665` — the emergency reclaim and its `Created`-based gate
- `docs/lessons/containers-docker/lesson-437-*` — why uptime measured the host
- `docs/lessons/process-method/lesson-285-*` — converge the brain, specialize
  the egress
- ADR-028 — why the Beelink is deliberately outside K3s
