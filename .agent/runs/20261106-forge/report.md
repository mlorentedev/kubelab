# Run 20261106-forge — report

Armed 2026-11-06T06:58Z, ended 2026-11-06T11:52Z. Reason: queue-empty (every item done or blocked on the owner).

## Landed
- #3149 — bee GitHub runner declared off and removed (#3080 AC1/AC2).
- #3163 — `gitea reconcile` exits 1 when a machine account owns a repository (AUTH-024 AC3).
- #3178 — AUTH-022 closeout: AC2 evidence, pool-review gaps fixed (agent under the machine-identity guards, rotate-token help derived), ADR-062 updated, spec archived. Closes #2577 (board: Done).
- #3177 — #3080 AC3: provision fails when a declared runner is not registered; failure message distinguishes unreachable / token refused / GitHub error / not registered; status report prints measured state. Closes #3080.

## Prod operations
- `make provision NODE=bee ENV=prod TAGS=gitea` twice from master after #3149: changed=3, then ok=53 changed=0 failed=0 (AUTH-022 AC2).

## Blocked / for the owner
- #3148 (AUTH-024), board Blocked: AC1 creation limit (instance-wide MAX_CREATION_LIMIT=0 vs per-account at creation), AC2 branch protection (for everyone vs operator whitelist), AC4 the `write:issue` decision. Forks in issuecomment-6679269609.

## Filed
- #3185 — flaky package-holds maintenance test under xdist (seen once on #3177).

## Notes
- Reviewer coverage: PR-Agent reviewed every PR; CodeRabbit was out of quota and Codex failed, both notices only. Every triage disclosed self-triage.
- Force-push was denied once; branches were updated by merging master instead.
- GraphQL secondary rate limit delayed lands; retried, no grant condition skipped.
