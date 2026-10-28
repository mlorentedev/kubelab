# Run autopilot-2026-10-28

Verdict: in progress (armed 2026-10-28T03:25Z, expires 12:25Z).

## Waiting on you (irreversible first)

- T1-T4 of the hard-reset test (B14), each followed by `make edge-boot-check`. The rpi4 second pass ran (ok=182 changed=1, the one change being apt's time-based cache refresh), and the plugged-in boot check passed 22/22 at 06:35.
- The Beelink provision with `-e base_system_release_holds=true`, after #2756 lands. It is the deliberate Docker move #2722 asks for.
- #2759 (deb822 sources) lands after that Beelink provision, not before.
- New names for you to confirm or rename (cheap follow-ups): the probe overrides `F2_WORK` and `F2_RESULT` and the verdict `F2_FIXTURE_UNREACHABLE` (#2760).

## Parked

- #2742 ANSIBLE-072: two forks on the issue (scope and rollout order); it changes the rpi4 and Beelink plays on your return list.
- #2722, the runner job timeout: the value lives in `infra/config/values/**`, outside this run's write paths, and needs your number. The smoke build (option A, ruled 06:16) follows #2756.
- #2758 ANSIBLE-074: the ace2 dry run with `TAGS=gh CHECK=1` hangs on the controller before connecting (no `ESTABLISH` after Gathering Facts at `-vvvv`). Being isolated: check mode or the tag.

## Done but unmerged

- #2749 #2733 recovery clears the failed notifier: CodeRabbit's lock race applied (e6a3bd33), CI running, then triage and land. #2757 follows it.
- #2756 #2722 CI engine held across provisions: pr-agent's two test findings applied (42aebed3), CI running.
- #2760 #2750 missing-fixture verdict: CI and review running.
- #2759 #2737 deb822 sources: held for the Beelink provision.

Landed this run: #2743, #2746, #2706, #2741, #2736, #2747 (05:34), #2748 (06:02), #2740 (06:03), #2752 (06:25).

## Ledger

| UTC | Item | Result | Evidence |
|---|---|---|---|
| 03:25 | arm | envelope 199bacb6 + rulings commit; inhibitor `claude-autopilot` sleep:idle:handle-lid-switch verified | `systemd-inhibit --list` |
| 03:25–03:44 | review dispositions #2741 #2743 #2740 #2706 | triage comments posted; #2741 cooldown per-semver assert (mutant red), #2706 ServerAlive stall bound (2 mutants red), #2743 runbook regenerate-in-place | PR comments 6459895864, 6459910394, 6459915900, 6459951807 |
| 03:25–03:44 | #1021 cross-link to #1102 | done | issuecomment-6459957069 |
| 03:25–03:44 | cold start (`make test-fast`, master) | 7719 passed, 19 skipped; no inherited red | bo7nihcwr exit 0 |
| 03:25–03:44 | node_maintenance comment | #2746 opened. The `make maintain` premise for the hub was wrong (gcp1 is in staging/prod inventories); dropped before commit | fa089970 |
| 03:25–03:44 | #2740 Tests red | real: inventory guard refused any `networking` key in SOPS; #2665 put edge secrets at `networking.edge`. Fix #2747 (guard derived from generator reads, 3 mutants red); then update-branch #2740 | #2747 |
| 03:25–03:44 | debt seen | `tests/` unlinted, 68 ruff findings: counted on existing #1292 | issuecomment-6460113045 |
| 03:44–04:05 | #2744 TOOL-126 | #2748 draft (6 mutants red); live audit waits for #2743's token on master, then rebase + ready | #2748 |
| 03:44–04:05 | #2741 second CodeRabbit review | applied both (check-ignore -v negation, lesson-518 relock), mutant red, re-pushed | issuecomment-6460217856 |
| 03:44–04:05 | #2736 pr-agent finding | applied (name each stale copy's path; FIX names the full `ansible` package), mutant red, re-pushed | issuecomment-6460241002 |
| 04:05 | #2742 ANSIBLE-072 | parked before claim (needs-decision). Deviates from the "spec fast + PR" ruling: 12 pulls in 11 roles, and it would change the rpi4/Beelink plays on your return list. Two forks posted | #2742 comment |
| 04:13–04:26 | landed #2743, #2746, #2706, #2741, #2736 | merged under the grant, `dotf pr triage-queue --pr N` rc 0 each | merged 04:13, 04:15, 04:18, 04:19, 04:26 |
| 04:26–04:30 | #2692 | `@dependabot recreate` after #2741 changed the lock; Dependabot closed it as no longer needed | PR closed 04:30 |
| 04:05–04:40 | ace2 PAT check | provision `TAGS=dev_node` ok=72 changed=5 failed=0; token reads a private repo with push. F2 fails: its fixture repository is gone, not the token | #2750 |
| 04:05–04:40 | #2726 | #2752: dev Pi-hole pinned to the edge's tag, test holds the two equal and every literal stack image versioned (3 mutants red). Found and filed #2753 SSOT-031, #2754 SSOT-032 (bug: dev n8n stack reads variables the config no longer emits), #2755 MON-013 | #2752 |
| 04:05–04:45 | #2722 | apt history shows the Docker move came from `base_system`'s dist-upgrade during a provision, not the timer. #2756: `base_system` holds a node's declared packages before its upgrade, release flag for one run, `package_facts` guard for a first provision (4 mutants red), lesson-645. Correction posted on the issue | #2756, issuecomment-6460839746 |
| 04:40–04:50 | #2747, #2748 review fixes | #2747 follows a keyword hand-off (2 mutants red); #2748's new phrasing test found "60 or 90 days" read as 90 only, regex fixed (2 mutants red) | 45a335a4, a97bc1e3 |
| 04:52–05:05 | #2749 review follow-up | CodeRabbit: a recovery could overtake a page in flight, newly reachable for first pages. Per-unit `flock` from state read to state write, notifier timeout 45→90s to hold the wait, test helper sentinel bug fixed, reset target read from `OnFailure=` (8 mutants red). #2747 triage posted | 05286907, issuecomment-6460989928 |
| 05:05–05:50 | #2740 Tests, #1196 | #2747 landed, #2740 updated and landed; a known Socket.IO flake on #2749 noted on #1196 | issue comment on #1196 |
| 05:05–05:50 | #2733 follow-ups | ticketed #2757 NOTIFY-011 (a unit slower than the TTL loses its recovery) and #2758 ANSIBLE-074 (ace2 dry run hangs) | #2757, #2758 |
| 05:05–05:50 | #2737 | #2759: Docker and GitHub CLI sources as deb822, old `.list` removed after the new source (10 mutants red); dry run blocked by #2758 | #2759 |
| 05:50 | rpi4 second pass (operator) | ok=182 changed=1 failed=0; the change is apt's `cache_valid_time` refresh, time-based, so converged | operator terminal |
| 06:16 | envelope widened by the operator | 17 items / 14 iterations; #2750 A, #2757 A, #2722 smoke build A | 70eb182a |
| 06:20–06:30 | #2749 CodeRabbit lock race | unit result read under the lock; new test red on the old template | e6a3bd33 |
| 06:20–06:30 | #2756 pr-agent findings | re-hold test now simulates each run's applied selections (gate mutant red); timer test runs the hold block with the engine already held (mutant red) | 42aebed3 |
| 06:25 | #2752 | triaged, landed | issuecomment-6462294391 |
| 06:25–06:35 | #2758 | `-vvvv`: the second play never connects; ace2 has no hung mount and passwordless sudo works | issuecomment-6462346657 |
| 06:25–06:35 | #2750 | fixture recreated private; probe verdict `F2_FIXTURE_UNREACHABLE` for a 404 (mutant red); F2 on ace2: `F2_OK`, probe PR closed, branch gone | #2760 |
| 06:35 | `make edge-boot-check VIA=tailnet` | 22/22 OK, rc 0, ruleset at 9.6s before networkd at 15.5s | read-only |

## Budget

Iterations: 9 / 14: (1) open-PR dispositions, #1021, node_maintenance comment, #2740 diagnosis; (2) #2744; (3) #2742 park and the land sweep; (4) ace2 PAT and #2692; (5) #2726; (6) #2722; (7) #2733 and the review follow-ups; (8) #2737; (9) #2750. Items: 14 / 17. No dollar figure exists for this run.

## Host suspend

Not yet checked (journalctl -u systemd-suspend.service at exit).

## Next action

To be written at exit.
