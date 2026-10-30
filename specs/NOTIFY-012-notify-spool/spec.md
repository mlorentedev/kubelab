---
id: NOTIFY-012-notify-spool
type: spec
status: active
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
- `--flush` delivers the spool oldest first, stops at the first refusal, and exits non-zero while notices wait. A notice older than `node_notify_spool_max_age_seconds` is dropped, with a line in the journal.
- Order with the live path: a notice is sent directly only when it holds the spool's lock and the spool is empty. Otherwise it is kept and the flush is started. A recovery never overtakes the failure it closes, which n8n's router would otherwise leave open as an alarm.
- A reminder of a page still kept is folded into it, and still renews the state.
- The exercise of a healthy unit (`make maintain-notify-test`) is never kept. It is sent directly and fails if n8n does not take it.
- The role adds the spool directory, `kubelab-notify-spool.service` and `.timer`, and enables the timer. It clears the failed state of `kubelab-notify@*` and `kubelab-notify-recovered@*` units, and leaves the spool unit alone.

Out:

- The pages lost before this change. Their payloads were never stored. Only the stale failed state is cleared.
- Coalescing across units. Each unit keeps its own notices.
- A delivery path that bypasses the edge. When the edge is down, the spool waits for it.

## Checklist

- [x] Failing tests first, on the Node harness (it runs the shipped script with shims) and in the role tests. Covered: refused page kept and counted; flush delivers once with the time; refused flush keeps the notice and fails; flush stops at the oldest; no overtaking, and the flush is started; refused recovery kept and closes the incident; reminder folded; outage past the TTL stays one incident; exercise not kept; half-written notice not delivered; old notice dropped; unit, timer, directory and cleanup.
- [x] Seven tests that encoded "a refused page is not recorded" were changed in the same commit. The #2733 age rules keep their tests, on a state with no page recorded.
- [x] Mutants red (16): direct write, no stop at the first refusal, fold that keeps LAST, no fold, overtaking, no flush start, no age drop, no time stamp, no removal after delivery, exercise kept, kept notice failing its unit, wide cleanup pattern, ungated cleanup, cleanup argv from the last word, a failed keep ignored, a keep that returns before writing. A spool name the script did not write was red before its fix.
- [x] Lesson: lesson-678.
- [x] A node provisioned with the role: the timer is active, the failed notifiers are cleared, and a rerun reports changed=0. ace2, 2026-10-30, from master at cd932def with `TAGS=maintenance`: two failed notifiers before, none after; timer enabled and active; spool 0700 root; rerun `changed=0`.

## Evidence

See the PR body of #2859, and the provision of ace2 in the PR that ticks the last item.
