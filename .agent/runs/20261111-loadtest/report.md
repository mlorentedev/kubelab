# Run 20261111-loadtest

- Armed: 2026-11-11 (envelope 39e83385), expires 2026-11-11T19:40:08Z.
- Ended: 2026-11-11T14:25Z, reason `goal-blocked`. The objective's remaining criterion (#3102 AC1, the Traefik CPU profile) needs pprof through the HelmChartConfig in `infra/ansible`, a frozen path. The only other candidate, #3294, changes the test's verdict and summary schema, which is a design call, not a defect.
- Host: wake-lock held (`caffeinate -i -s -t 43200`) for the whole window.

## Items

| Item | Outcome | Evidence |
|---|---|---|
| #3102 what starts the stall | Partly done, then parked (board: Blocked) | #3274 (timeline sampler) and #3296 (finding: the knee is a cold connection burst, not warm capacity) merged. AC1 options (A/B) posted on #3102. |
| #3295 sampler skew and ssh cost (found while working #3102) | Done, closed | #3298 merged at f303efc0. `make test` 9785 passed. Mutation red on both new guards. Cost at rest measured on staging: median ace1 cores 0.300 / 0.364 / 0.305 (none / handshake per read / one connection). |

## Filed

- #3294 warm capacity apart from the cold burst (Backlog, owner's design call).
- #3295 (closed by #3298).

## Knowledge

- lesson-736 (cold connection burst), lesson-737 (rate over the client's clock).
- Runbook `docs/runbooks/load-test.md`: what the knee measures, the sampler's cost and clock.

## Merges

#3274, #3296, #3298, each through `dotf pr land` with CI green, CLEAN, a `## Review triage` comment and the triage queue at 0. All reviewed by PR-Agent only; CodeRabbit and Codex did not review.

## Waiting on the owner

1. #3102 AC1: option A (expose pprof in staging for one profile, then remove it) or B (close AC1 on the current evidence).
2. #3294: whether to split the verdict into warm and cold figures.
