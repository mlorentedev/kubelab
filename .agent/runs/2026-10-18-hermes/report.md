# Run 2026-10-18-hermes

run 2026-10-18-hermes: ended queue-empty after 1 iteration / about 5h (window 10:40Z to 18:40Z) - 1 done and merged, 2 parked, 0 irreversible. Nothing landed in prod from this run.

## Waiting on you (irreversible first)

- Nothing irreversible. Nothing was applied to ace2 beyond the probe containers, each removed by the task's `always` block (provision recap changed=0 on every run).
- #2487 (fix #2380) merged by the grant at `fee2304` (six conditions held: Tests green on the head, clean, two triage tables, no grant file touched). Dry-run-only change, so no ace2 apply was needed.
- #2299 parked (Blocked): the codified fallback probe builds and starts a throwaway gateway on ace2 but `hermes chat` answers `invalid_params` on every retry, so the fallback is never exercised. Options: (A) bisect with a minimal config in the throwaway to tell "probe lacks mounts" from "fallback chain broken in the live config" (recommended); (B) keep the manual runbook sequence and close as won't-do. Work is on branch `feat/hermes-fallback-probe`, off by default, no PR.
- #2175 not claimed: a decision ticket and the top-tier advisor dispatch was refused (this machine has no declared identity in `machine.json`). Options A (healthcheck plus systemd watcher through the notify fabric, recommended) or B (Uptime Kuma push monitor) are on the issue.

## Done

- #2380 -> #2487, mutation-proven on both guarded tasks and on the inverted guard.
- #2461 live check: the triage memory file exists on ace2, hash-only, and the 14:10Z and 15:10Z runs ended `wakeAgent=false`. Not observed: survival across a gateway recreate.

## Evidence

- `make provision NODE=ace2 ENV=prod TAGS=agent_stack CHECK=1`: ok=144 changed=0 failed=0.
- Probe runs: five, all `changed=0` outside the probe, all cleaned up.
- tests/test_hermes_persona.py 13 passed; tests/test_hermes_fallback_probe.py 6 passed on the parked branch.

## Budget

1 of 8 iterations used; no consecutive-failure trip for the run (the 3x breaker tripped on #2299 only). The queue filter held three items, so the run ended there.

## Host

The wake-lock (`caffeinate -i -t 30000`) was held for the whole window; no suspend observed.

## Next action

Answer #2299 (A or B) and #2175 (A or B).
