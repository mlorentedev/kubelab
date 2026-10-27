# Pilot report — autopilot-2026-10-27-night

Draft, updated through the run. Envelope: `.agent/unattended.yml` (expires 2026-10-27T15:00:00Z).

## Host
- Sleep inhibitor held for the window (`systemd-inhibit --what=idle:sleep`, until ~15:00Z).

## Landed under the grant
- #2718, #2719, #2709, #2715, #2723, #2725, #2727, #2721 (closed #2720), #2731.

## Open, mine (state at writing)
- #2724 Pi-hole pin: scan widened in `605b1847` (third PR-Agent pass), awaiting CI.
- #2729 notifier ordering: awaiting the PR-Agent re-run and CI.
- #2730 edge boot check: redesigned after a live read-only run on rpi4 (journal lost the boot's first 28 s; now reads unit timestamps); live run all `OK`. Lesson 641.
  An independent adversarial review then returned FAIL: the no-uplink case could not pass (the liveness unit's page also fails with no route out). Fixed, plus AP/DHCP/LAN-DNS probes; 22 checks `OK` live. Tickets filed: #2732 NET-017 (T4 hypothesis: LAN address needs a carrier, may take DNS down), #2733 OBS-039 (an undelivered page stays a failed unit).

## Notes against the envelope
- #2730 executable LOC: script ~110, toolkit ~70, Makefile/tasks ~10 (tests ~400). Over `max_loc` 300 in sum; stated, not hidden: the script, its CLI and its runbook are one deliverable the operator asked for.
- Pushed branches got `git merge origin/master` commits instead of rebases: force-push is denied.
- #2724: a test rename was made unattended (no identifier exposed outside the test module).

## Incidents
- One raw networkd journal line printed the uplink's DHCP lease address and gateway (private RFC1918) into the session transcript. Transcript only: not in the repo, a PR or an issue. Later remote output was filtered.

## For the operator (prod actions, in order)
See the session journal; summary filled at close.
