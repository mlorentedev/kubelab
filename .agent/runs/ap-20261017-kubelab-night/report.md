# Autopilot run ap-20261017-kubelab-night

**Verdict:** ended `queue-empty` after 3 items in about 1h30 (armed 07:36Z, closed about 09:05Z; the envelope ran to 17:36Z): 1 PR merged, 2 PRs open for you, 2 parked, 0 irreversible actions. Question it answers: what is waiting on a human? Two PRs and two decisions; nothing landed that a revert cannot undo.

## Waiting on you, irreversible first

Nothing irreversible was done. In order of what unblocks the most:

1. **Merge PR #2394** (`fix/ci-pin-go-tools`, head `a82de317`): pins `gosec@v2.29.0` and `govulncheck@v1.7.0` in `.github/workflows/ci-pipeline.yml` (workflow file, so the run never merges it). Without it every `apps/api` PR fails at `go install govulncheck@latest` (needs Go 1.26, job runs 1.25). Triaged; both pins were built by hand under `GOTOOLCHAIN=go1.25.14`. Closes #2389.
2. **Then PR #2387** (`fix/api-health-honest`, closes #1736): honest `/health` `/healthz` `/ready`. Its only red check is `API / CI + Build for api`, which is #2389. After #2394 merges, update #2387 from master and let the API job run; I did not claim it fixed before that job has gone green. Triaged. One decision inside it for you: `/ready` does not fail when Beehiiv is down (ticket asked it to), it reports `degraded` with 200, because a third-party outage must not pull pods out of rotation.
3. **#1320 parked** (OBS-017): needs the minimum-samples bar ratified. Options A (>= 3 everywhere, widens the `disk-rules`/`quota-rules` windows) or B (per-rule justification list; recommended). Board: Blocked.
4. **#1306 parked** (OBS-016): the detector's placement is a design call and AC2 needs a deliberate fault on a live node. Options A (per-node timer into NOTIFY-001; recommended, rehearsed on a throwaway container) or B (workstation command). Board: Blocked.

## Parked

#1320 and #1306 above; each carries ERROR / WHY / FIX with two options on the issue.

## Done and merged

- **#2401** (`Refs #2243`, merge commit `2d992b48`): removed `toolkit monitoring backup` / `restore`, rewrote the runbook's backup section around `node_backup`, widened the guard to every tracked file after the reviewer pointed out its scope. #2243 stays open for the restore drill and the rpi3 crontab (live node changes, not done unattended).

## Also produced

- **#2136**: per-node rollout plan for Docker's address pool posted on the issue (nothing executed). Notable finding there: `provision-ace2.yml:287` and `tests/test_agent_egress.py` build the agent egress block from `trusted_cidrs + [docker_address_pool_base]`, so the pool variable has a second consumer.
- **#2386**: generator needs a separate readiness probe path (filed). **#2389**: the CI breakage (filed, PR #2394).
- Closed #2383 after you deleted the Hetzner snapshot.

## Skipped on purpose

#686 (three sub-items, one needs a volume assessment before enabling), #694 (touches `renovate.json`, which a peer's #2395 holds), #248 and the CERT/HELM chores (multi-step migrations of live TLS and charts, fail the 3 a.m. test).

## Evidence index

| Item | Command | Result |
|---|---|---|
| #2243 / #2401 | `make test` before the PR | 5671 passed, 19 skipped |
| #2243 | `pytest tests/test_kuma_dr_is_node_backup.py` | 3 red before the change, 4 green after; widened guard red with a stray line in `CHANGELOG.md`, restored |
| #1736 / #2387 | `make test`; `go test -race ./internal/health/` | 5665 passed; 6 mutations red, plus 1 for the lock fix |
| #2389 / #2394 | `GOTOOLCHAIN=go1.25.14 go install ...@v1.7.0` and `...@v2.29.0` | both built; binaries removed afterwards |
| merge | `gh api repos/mlorentedev/kubelab/pulls/2401` | merged, `2d992b48` |

## Budget spent

3 items of 6; about 1h30 of the 10h window. No dollar figure exists: the provider exposes none here.

## Host-suspend line

`caffeinate -i -t 36000` held for the window and every poll answered without a gap. Inferred from uninterrupted polling, not measured by the OS.

## Disclosed lapses

- A first attempt to edit the workflow was denied by the permission classifier; I stopped, asked, and redid it after your explicit go-ahead. Nothing was worked around.
- While checking the pins I ran `go install` which put two binaries in the mise Go bin directory; removed.
- GraphQL hit its secondary limit twice from parallel polling; I moved to REST and slower polls.

## The one next action

Merge #2394, then ask for #2387 to be updated from master and its API job to be watched.
