# Run ap-20261022-kubelab-console004

Verdict: ended by queue exhaustion inside the envelope (armed 2026-10-22T07:36Z, expires 15:30Z). Epic CONSOLE-004 (#2570). Everything mergeable under the grant was merged; the rest waits on the operator.

## Waiting on the operator
1. #2570: answer A or B. ADR-051's Postgres substrate (atlas schema, driver, DSN, migration Job) does not exist. (A) slice 0 inside CONSOLE-004, (B) a separate ticket first. Reader and webhook slices proceed meanwhile; the read model, queue endpoint and outbox cannot.
2. #2633 (Authelia `theme: auto`): merge, apply, check in a browser. AUTH-023 #2632 closes with it. Deliberately not landed by the run (apply step is operator-owned).
3. Gitea fixture: recording needs a token behind Authelia, so the Gitea adapter cannot be built unattended.
4. Create the GitHub App for the read adapter (task in `tasks.md`).
5. Outside the envelope: CONSOLE-006 #2588 (label set: toolkit/ and common.yaml, remote mutation), CONSOLE-005 #2587 (retire Vikunja after parity plus the 14-day A8 window), CONSOLE-007 #2586.
6. #2443 WIP limit (CONSOLE-004 was started over it with `wip_override`).

## Parked
- #2570 Postgres substrate: options A/B above, commented on the issue. Lesson-617 filed.

## Done and merged under the grant
#2623 (ADR-066 A1/A2/A7/A8 corrections), #2631 (decisions before code), #2634 (Vikunja token expiry), #2636 (HMAC verification), #2640 (lesson-617), #2635 (forge-neutral reader and GitHub adapter, `49416d0`), #2648 (spec task ticks, see below). Operator-merged earlier in the lane: #2618, #2585, #2575.

## Evidence
- #2635: `go test ./internal/forge/` green; mutation `next = ""` turns `TestGitHubReaderFollowsPagesAndSendsSince` and `TestGitHubReaderStopsAtThePageCap` red; page-cap mutant proven by timeout (exit 124).
- `dotf pr triage-queue --pr 2635`: `[OK] no reviewer output is awaiting a disposition`, then `[MERGED] #2635 at 49416d0`.
- Reviewers: Codex had no quota, CodeRabbit was rate limited, PR-Agent reviewed (three rounds on #2635, two fixes applied, test gaps ticketed in `tasks.md`).
- #2631 and #2636 merged with the `merged-unreviewed` declaration (docs/clean PRs, no reviewer named a finding).

## Incidents
- Operator merged #2585 before my push; corrections re-opened as #2623. I had edited #2585's body/triage by mistake (disclosed).
- Force push is on the Stop List: a rebased branch was rebuilt from origin and the edit re-applied, plain push.
- GitHub GraphQL secondary rate limit blocked `gh pr view/ready/checks`, `dotf pr land` and `add-to-project`; used REST and waited.
- Advisor was overloaded twice; only mechanical work proceeded in those windows.

## Budget and host
Wake-lock `caffeinate -i -t 28000` was running; no suspend was observed. No dollar figure.
