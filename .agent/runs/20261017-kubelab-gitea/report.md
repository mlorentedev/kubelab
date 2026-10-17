# Run 20261017-kubelab-gitea: ended queue-empty

Verdict: ended `queue-empty`. 3 queue items: 1 merged, 1 proposal posted, 1 parked. Nothing irreversible is waiting on you; the Gitea 1.27.3 upgrade itself was done and verified before arming.

## Waiting on you
- #2375 (OPS-038) AC8 and the runner check, parked (label `blocked`, board Status Blocked). Options:
  - A: push a throwaway branch (not `personal/resume`) that triggers a workflow, to measure act_runner 0.2.13 against Gitea 1.27.3 and the `concurrency` behaviour.
  - B: close AC8 against OPS-034 (#2063) and run the measurement as its step 1.
- #2063 (OPS-034): proposal comment posted (https://github.com/mlorentedev/kubelab/issues/2063#issuecomment-6231593397). It needs your go on step 1 and a maintenance window for the runner restart. The live runner was not touched.
- #2409 (OPS-040): new debt ticket, declare human members of the Gitea orgs in `common.yaml` so the reconciler applies them (`operator` sees only public repos today). Backlog, P2. Not implemented.
- Carried over, not mine: delete the old Default-workspace Anthropic key after 2026-10-17; #1860, #1752, #1701, #2342; #1813 sign-out is with session fix-sso-signout-1813.

## Parked
- #2375 AC8 and runner 0.2.13 check: reason, an unmeasured runner needs a push that can trigger a workflow and the envelope forbids touching `personal/resume`; unblock cheapest with option A.

## Done and merged
- #2408 (closes #2385, OPS-039): the 23 stale merge bases measured on 1.25.5 (snapshot 13893d74) are 0 on the first 1.27.3 snapshot (82b4bf47); the drill now fails on any stale row. Merged as 2e2587ca with `--match-head-commit`.
- Before arming, same session: #2371, #2376, #2379, #2381, #2384.

## Evidence
- `poetry run pytest -q --no-cov tests/test_gitea_upgrade_probe.py tests/test_gitea_drill.py`: 50 passed.
- `make backup-drill-gitea ENV=prod HOST=ace2`: "gitea doctor check --all is clean", 5 repositories restored from 82b4bf47.
- #2408 head d0954349: Tests, Validate, hygiene, attestation green; `review-attestation` success "a review happened"; `dotf pr triage-queue --pr 2408` exit 0.
- Reviewers: PR-Agent reviewed; Codex and CodeRabbit hit usage limits (no review from them). Triage comment: pull/2408#issuecomment-6231927044.

## Budget
3 items of 3, 1 PR, about 2 h of the 10 h window. No dollar figure exists. GitHub GraphQL had a secondary limit early on; REST was used and recovered later.

## Host
`caffeinate -i -t 36000` was running; the window was covered.

## Next action
Answer option A or B on #2375, then OPS-034 step 1.
