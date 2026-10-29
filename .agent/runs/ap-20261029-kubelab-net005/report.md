# Run ap-20261029-kubelab-net005

Verdict: ended 11:05Z, reason `queue-empty`: every remaining item waits on a step of yours (#2742 PR 2 on your ruling at #2789's merge and the spec question, #2776 on #2791 and the T3 re-run, #2675 on the frozen `CLAUDE.md` line, #2758 on your check-mode run). 12 PRs landed. 2 are open and left to you, both green and CLEAN with every reviewer finding disposed: #2789 and #2791. Repo-wide `dotf pr triage-queue` exits 0. Nothing is half-done on a branch without a PR.

## Waiting on you (irreversible and urgent first)

1. **#2777, the edge's `vpn.kubelab.live` pin is missing now.** cloud-init rewrote `/etc/hosts` at the 07:33 boot, so the `KUBELAB DNS RESILIENCE` block is gone until a provision puts it back. #2788 is on master (10:27): `make provision NODE=rpi4 ENV=prod TAGS=base,dns`, the same again for `changed=0`, then reboot the edge, `make edge-boot-check`, read `/etc/hosts` for the block and `cloud-init status` for `disabled`.
2. **#2789, the two rulings #2742 asked for, and its merge.** The PR takes (A) whole compressed size when the node does not hold the tag, and a budget as an include default of 1800 s; an estimate that cannot be made refuses. CodeRabbit argued the other side of (A) (a held tag that moved counts 0); `c399a3c2` adds `image_pull_timeout_seconds` as the lever either way. Merging is the ruling; overrule in a review instead. Also: whether PR 2 (the other pull sites) goes through `/spec init`.
3. **Open WebUI on ace2 has been down since the 2026-10-26 boot**: the image is not on the node. After #2789: `make provision NODE=ace2 ENV=prod TAGS=agent_stack EXTRA='image_pull_allow_slow=true'` (about 73 minutes of pull at 2970 kbit/s). A second run needs no override.
4. #2759 rollout provisions (deb822 sources), as listed on the PR.
5. Edge gateway: `make provision NODE=rpi4 ENV=prod TAGS=gateway` for #2781 and #2790 (and #2791 if you land it), then `make edge-boot-check`. Until #2791 is merged and provisioned, the check FAILs on `kubelab-edge-lease-check` or `kubelab-edge-shaper` if either is still starting: that is #2786, not a regression.
6. The rpi4 play for #2775's guard: `make provision NODE=rpi4 ENV=prod` from the LAN.
7. Stack units for #2783 and #2784: `TAGS=glances` on bee, rpi3, ace1, ace2 and rpi4; `TAGS=services` on bee and rpi3; `TAGS=agent_stack` on ace2 (after item 3).
8. #2785: `make provision NODE=rpi4 ENV=prod TAGS=tailscale` twice, the second for `changed=0`; then `systemctl cat tailscale-watchdog.service` on the edge. That tag also runs `dns_resilience` (tagged `dns, tailscale`), so it restores the vpn pin of item 1 too, until the next reboot.
9. ace1 lacks the `dns_resilience` block too (its `/etc/hosts` dates from 2026-03-17): `make provision NODE=ace1 ENV=staging TAGS=dns`.
10. #2758: the check-mode command on the issue.
11. B12: `changed=0` on a second full rpi4 provision, then the soak.
12. T1, T2 and T3 of the hard-reset test (B14) again, each followed by `make edge-boot-check`.
13. The D7 guard question on NET-005.
14. `CLAUDE.md` is frozen for this run: its RPi4 Tailscale flags line still lists three flags and calls the watchdog hand-made (#2675 stays open for it).

## Parked

- #2787 NOTIFY-012: a LAN node's failure notice is lost while the edge is down. Its proposal is marked "to decide" (spool and retry, or report the count), so it is not worked unattended.
- #2758 ANSIBLE-074: needs a provision that applies the role, which is yours.

## Done but unmerged

- #2791 (#2786): every shipped oneshot gets a finite start timeout, fleet test included. PR-Agent's three findings on the test applied in `240caa6e` (systemd's last-assignment rule, every span unit, a sample floor); `206391d3` merges master and updates the lab-edge runbook. #2786 is not in the envelope's queue filter, which also names more items than `max_items` allows, so it is left for you rather than landed under the grant.
- #2789: by design, see item 2. `e261243c` drops an unmeasured claim (that a retry keeps the layers already fetched) from the include, lesson-655 and the body. Its `Tests` failure on `c399a3c2` was the Loki harness's `docker run` exiting 125 on the runner, unrelated, filed as #2792.

Landed this run: #2773 (06:12), #2759 (06:34), #2778 (07:21), #2780 (08:00), #2779 (08:03), #2782 (08:04), #2781 (08:30), #2783 (08:33), #2784 (09:32), #2785 (09:41), #2790 (10:26), #2788 (10:27).

Filed this run: #2786 (PR #2791), #2787 (parked), #2792 (TEST-009, Backlog: the Loki test harness hides Docker's stderr). #2758 set to Blocked on the board: it waits on your check-mode run.

## Ledger

| UTC | Item | Result | Evidence |
|---|---|---|---|
| 05:43 | arm | envelope `daf87a6e`, B14 tickets named in `ee66e30c` | run branch |
| 06:12 | #2773 | landed | merged |
| 06:34 | #2759 | landed | merged |
| 07:21 | lesson-650 | unmeasured claim dropped | #2778 |
| 08:00 | #2722 corrections | the smoke build's messages match what was measured | #2780 |
| 08:03 | NET-005 B14 | hard-reset runs recorded, B14 kept open | #2779 |
| 08:04 | #2775 | the edge's LAN guard refuses before any role changes the edge | #2782 |
| 08:30 | #2774 | the boot check waits out the liveness grace | #2781 |
| 08:33, 09:32 | #2776 | stack units settle before compose; their tailnet wait runs outside the start job | #2783, #2784 |
| 09:41 | #2675 | the watchdog rendered by the `tailscale` role, bounded; off removes it | #2785 |
| 09:00–10:00 | #2742 | PR 1 with both rulings stated; site table and third fork on the issue | #2789, issuecomment-6493194958 |
| 09:00–10:00 | #2777 | cloud-init stopped on the edge; runbook row after #2785 | #2788 |
| 09:30–10:00 | #2776 boot check | judged by each running start job's own timeout (lesson-656) | #2790 |
| 10:05 | #2786 | filed during #2776; five oneshots bounded, fleet test | #2791 |
| 10:26 | #2776 boot check | landed after triage (PR-Agent only; CodeRabbit and Codex at their limits) | #2790 |
| 10:27 | #2777 | landed after triage (same reviewers) | #2788 |
| 10:30 | #2789 | triage addendum; unmeasured retry claim dropped; CI flake filed | `e261243c`, #2792 |
| 10:35 | #2786 | fleet test reads timeouts as systemd does; runbook | `240caa6e`, `206391d3` |
| 10:38 | #2758 | Blocked on the board, waiting on the operator's check-mode run | board |
| 11:00 | #2789, #2791 | CI green on `e261243c` and `206391d3`; PR-Agent re-reviews disposed (no new finding on #2789; two stale and one declined on #2791) | triage addenda |
| 11:05 | run | ended, queue empty | this report |
