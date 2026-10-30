---
id: NOTIFY-012-notify-spool
type: spec
status: archived
created: "2026-10-30"
owner: manu
issue: "kubelab#2787"
---
# NOTIFY-012: Notify spool

## Intent

A failure notice from a node behind the lab edge is lost while the edge is down. On a LAN node DNS goes through the edge's Pi-hole, so `kubelab-notify@` failed at once on resolution and nothing sent the notice later. On 2026-10-29 ace2 held six failed notifiers, four of them from the B14 window of #2661, and the operator heard of none of those failures. The operator chose the spool and a timer on #2787, and asked that provisioning clear the failed notifiers with no manual reset.

## Scope

In:

- `kubelab-notify.sh` keeps a notice that n8n does not take in `node_notify_spool_dir`, and counts it as sent. The file is named `<nanoseconds>-<unit>` and is written aside and renamed in. The notice's title carries the time it happened, `(at <UTC>Z, delivered late)`.
- `--flush` delivers the spool oldest first, stops at the first refusal, and then exits non-zero, which keeps the spool unit failed while notices wait. A flush that cannot take the spool's lock within the lock wait leaves the spool to the run holding it and exits 0. A notice older than `node_notify_spool_max_age_seconds` is dropped, with a line in the journal.
- Order with the live path: a notice is sent directly only when it holds the spool's lock and the spool is empty. Otherwise it is kept and the flush is started. A recovery does not overtake the failure it closes, which n8n's router would otherwise leave open as an alarm. A failure already kept is held ahead by the spool's lock and the empty-spool check. A failure still on the wire is held ahead by the unit's own lock, which the recovery waits for: that holds because `node_notify_lock_wait_seconds` (40) outlasts one delivery's worst case (30), which a role test pins.
- A reminder of a page still kept is folded into it, and still renews the state.
- The exercise of a healthy unit (`make maintain-notify-test`) is never kept. It is sent directly and fails if n8n does not take it.
- The role adds the spool directory, `kubelab-notify-spool.service` and `.timer`, and enables the timer. It clears the failed state of `kubelab-notify@*` and `kubelab-notify-recovered@*` units, and leaves the spool unit alone.

Out:

- The pages lost before this change. Their payloads were never stored. Only the stale failed state is cleared.
- Coalescing across units. Each unit keeps its own notices.
- A delivery path that bypasses the edge. When the edge is down, the spool waits for it.
- Exactly-once delivery. Delivery is at least once by choice: a request n8n accepts but answers too late is also kept, and delivered again. The failures #2787 measured (curl 6 and 28, while resolving) never reach n8n.
- A payload n8n refuses for good, or a notice file left empty by a power cut (no fsync before the rename), holds every later notice of the node behind it until the age drop, with the failed spool unit as its trace. Accepted: order is the point of the spool, and the drop bounds the wait.
- Clocks that jump. Names, the age drop and the title read the wall clock, which the RPi4 boots without: #2866 (NOTIFY-013) decides it before rpi4 gets the role.

## Checklist

- [x] Failing tests first, on the Node harness (it runs the shipped script with shims) and in the role tests. Covered: refused page kept and counted; flush delivers once with the time; refused flush keeps the notice and fails; flush stops at the oldest; no overtaking, and the flush is started; refused recovery kept and closes the incident; reminder folded; outage past the TTL stays one incident; exercise not kept; half-written notice not delivered; old notice dropped; unit, timer, directory and cleanup.
- [x] Seven tests that encoded "a refused page is not recorded" were changed in the same commit. The #2733 age rules keep their tests, on a state with no page recorded.
- [x] Mutants red (16): direct write, no stop at the first refusal, fold that keeps LAST, no fold, overtaking, no flush start, no age drop, no time stamp, no removal after delivery, exercise kept, kept notice failing its unit, wide cleanup pattern, ungated cleanup, cleanup argv from the last word, a failed keep ignored, a keep that returns before writing. A spool name the script did not write was red before its fix.
- [x] Lesson: lesson-678.
- [x] A node provisioned with the role: the timer is active, the failed notifiers are cleared, and a rerun reports changed=0. ace2, 2026-10-30, from master at cd932def with `TAGS=maintenance`: two failed notifiers before, none after; timer enabled and active; spool 0700 root; rerun `changed=0`.

- [x] Independent review findings dispositioned (PASS-WITH-GAPS, before the pool review). Five more mutants red, 21 in all: the spool's lock dropped from the direct-send check, a flush without its lock, a reminder folded into another unit's page, and the cleanup gate as `>= 0` and as `== 0`. The no-removal mutant now goes red by an assertion, not by the harness timeout.

- [x] Pool review PASS (`review.md`, nan/mimo-v2.6-flash, at `be11baf5`). Its three Minor findings (a kept reminder's stale count, the role's `reset-failed` race, a backlog that outlasts one flush) are #2870. F5 is answered: `make maintain-notify-test NODE=ace2 ENV=prod` delivered through live n8n on 2026-10-30, after the provision from `cd932def`, and the spool held 0 notices afterwards.

## Promotion candidates

- [x] Lesson? yes: docs/lessons/observability/lesson-678-a-retry-inside-one-request-cannot-outlive-an-outage-of-its-path.md (and lesson-647 qualified)
- [x] ADR? no: the spool is local to the node_notify role and changes no contract between components
- [x] Pattern? no: a durable spool in front of a webhook is used by this role only so far

## Evidence

See the PR body of #2859, and the provision of ace2 in the PR that ticks the last item.
