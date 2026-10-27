# Pilot report — autopilot-2026-10-27-night

Final, 10:25Z. Envelope: `.agent/unattended.yml` (expires 2026-10-27T15:00:00Z).

## Host
- Sleep inhibitor (`systemd-inhibit --what=idle:sleep`) held from arming until the run ended `queue-empty`, then released at ~10:35Z.

## Landed under the grant
- #2718, #2719, #2709, #2715, #2723, #2725, #2727, #2721 (closed #2720), #2731.
- #2724 Pi-hole pin (09:4xZ), two stale PR-Agent findings declined with reasons.
- #2730 edge boot check (~10:05Z): expected page read from the unit's `OnFailure=` (checked live), four repeat findings declined; CodeRabbit clean. Its only overlap, `toolkit/README.md` with #2656 (draft, idle since 2026-10-23), is a hunk 118 lines away.
- #2729 notifier ordering (~10:15Z, closed #2728): two PR-Agent findings applied in `9fff8024` (recovery-only consumers counted, templated role names refused; both mutation-killed).

## Open, mine
- None. #2706 (`.github/**`, the operator's) and #2672 (after B3) were never under the grant.

## Tickets filed this run
- #2722 OPS-050, #2726 DNS-008, #2732 NET-017, #2733 OBS-039 (Backlog, P2, on the board).

## Adversarial review
- An independent review of #2730 returned FAIL: the no-uplink case could not pass on real systemd (the page it sends fails too), and "active" is not "serving" for the AP and DHCP. Fixed in `8228fed0` (the page is expected, `hostapd_cli` state and a listening DHCP port, LAN DNS answering). Its two edge behaviours that need a decision are #2732 and #2733.

## Not picked up
- #2726 DNS-008: parked (scope-violation): its fix pins `infra/stacks/services/core/pihole/compose.yml`, outside `write_paths`.
- #2722 OPS-050, #2732 NET-017, #2733 OBS-039: each needs a decision (options in the issue).

## Notes against the envelope
- #2730 executable LOC: script ~110, toolkit ~70, Makefile/tasks ~10 (tests ~400). Over `max_loc` 300 in sum; stated, not hidden: the script, its CLI and its runbook are one deliverable the operator asked for.
- Pushed branches got `git merge origin/master` commits instead of rebases: force-push is denied.
- #2724: a test rename was made unattended (no identifier exposed outside the test module).

## Incidents
- One raw networkd journal line printed the uplink's DHCP lease address and gateway (private RFC1918) into the session transcript. Transcript only: not in the repo, a PR or an issue. Later remote output was filtered.

## Stop
`queue-empty` at 10:20Z. Every queue item has landed, is closed, or waits on the operator: #2685's code landed in #2687 and the issue closes at B6, #2678 is parked, #2706 is the operator's. All PRs I opened this run are merged. The repo-wide `dotf pr triage-queue` exits 0.

## For the operator (prod actions, in order)
Run them from the deploy checkout once it is synced: `git -C ~/Projects/worktrees/kubelab/master-deploy fetch origin && git -C ~/Projects/worktrees/kubelab/master-deploy checkout --detach origin/master`.

1. `make deploy TARGET=dns ENV=prod`: #2724's pin and #2725's cache flush. Pi-hole is recreated once, because its image string changes.
2. `make deploy TARGET=vps ENV=prod`, twice: #2707. The second run must report `changed=0`.
3. `make provision NODE=bee ENV=prod TAGS=maintenance,glances`, **before 2026-10-28 00:27**: #2719, #2710 and #2697.
4. `make provision NODE=rpi3 ENV=prod`: #2697 and #2729.
5. `make provision NODE=ace2 ENV=prod TAGS=agent_stack,maintenance,glances`: #2703, #2710 and #2697.
6. `make provision NODE=ace1 ENV=prod TAGS=maintenance,glances`: #2710 and #2697.
7. `make provision NODE=rpi4 ENV=prod TAGS=gateway,maintenance`: #2730 and #2710. Then `make edge-boot-check` must be all `OK`. Then the hard-reset cases T1 to T4 together (`docs/runbooks/lab-edge.md`, "Hard-reset test"), with the evidence under `### B14-EVIDENCE`. T4 measures #2732.
8. `TAGS=maintenance` on vps and gcp1: #2710.
9. After the provisions, no node's boot journal should carry `Failed to enqueue On(Success|Failure)=` (#2729).
10. After 2026-10-28 00:04Z: read that night's prune run (#2708).
11. #2706 is yours to review and merge. #2672 merges after B3 and the staging validation.
