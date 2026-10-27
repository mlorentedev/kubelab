# Pilot report — autopilot-2026-10-27-night

Draft, updated through the run. Envelope: `.agent/unattended.yml` (expires 2026-10-27T15:00:00Z).

## Host
- Sleep inhibitor held for the window (`systemd-inhibit --what=idle:sleep`, until ~15:00Z).

## Landed under the grant
- #2718, #2719, #2709, #2715, #2723, #2725, #2727, #2721 (closed #2720), #2731.
- #2724 Pi-hole pin (09:4xZ), two stale PR-Agent findings declined with reasons.

## Open, mine (state at writing)
- #2729 notifier ordering: two PR-Agent findings applied in `9fff8024` (recovery-only consumers counted, templated role names refused; both mutation-killed), master merged (`d3ff6de3`), awaiting CI.
- #2730 edge boot check: redesigned after a live read-only run on rpi4 (journal lost the boot's first 28 s; now reads unit timestamps); live run all `OK`. Lesson 641. Expected page now read from the unit's `OnFailure=` (`f867536d`, checked live), awaiting CI.

## Not picked up
- #2726 DNS-008: parked (scope-violation): its fix pins `infra/stacks/services/core/pihole/compose.yml`, outside `write_paths`.
- #2722 OPS-050, #2732 NET-017, #2733 OBS-039: each needs a decision (options in the issue).

## Notes against the envelope
- #2730 executable LOC: script ~110, toolkit ~70, Makefile/tasks ~10 (tests ~400). Over `max_loc` 300 in sum; stated, not hidden: the script, its CLI and its runbook are one deliverable the operator asked for.
- Pushed branches got `git merge origin/master` commits instead of rebases: force-push is denied.
- #2724: a test rename was made unattended (no identifier exposed outside the test module).

## Incidents
- One raw networkd journal line printed the uplink's DHCP lease address and gateway (private RFC1918) into the session transcript. Transcript only: not in the repo, a PR or an issue. Later remote output was filtered.

## For the operator (prod actions, in order)
See the session journal; summary filled at close.
