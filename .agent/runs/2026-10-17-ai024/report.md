# Run 2026-10-17-ai024

run 2026-10-17-ai024 ended 2026-10-17T06:20Z (queue empty for this objective, inside the window), 1 PR merged by hand, 1 awaiting the operator, 0 parked. Question it answers: what waits on a human, and is anything irreversible? Yes, one thing: #2373 changes prod ingress and is yours to merge.

## Waiting on you, irreversible first

1. **#2373** (prod ingress, Grafana API token route). Head b5a5de4b, Tests green, review-attestation green, triaged under `## Review triage`. Until it merges, the weaker Authelia `/api/` bypass from #2369 stays live in prod (Basic credentials can be tried on the public host). The only failing check is GitGuardian "Base64 Basic Authentication": a fake value in an earlier test commit, now built at runtime; dismiss it as a false positive in the GitGuardian dashboard. After the merge: no header gives the portal redirect, a `glsa_` token gives 200, Basic and a token plus Basic give the portal redirect.
2. Console key: the old Default-workspace Anthropic key can be deleted from 2026-10-17 if nothing broke (carried over).

## Parked

None.

## Done and merged

- **#2370** (AI-024 spec, docs and tests only) merged as f7d55c62 under the standing grant: CI green on cb26787b, mergeState CLEAN, no peer PR on its paths, five `## Review triage` tables posted (PR-Agent five passes, CodeRabbit one). Applied from review: fail-closed mail check with aligned DMARC and Zoho's own authserv-id, mail spend cap per hour, outbound approval default, daylight-saving rule, a new ledger entry makes the report non-silent, Stage 2 now describes the Traefik route.
- **#2365** (web search) merged earlier by the operator; stage 1 proven live on ace2 (provision changed=12 then 0).

## Evidence

| Item | Command | Result |
|---|---|---|
| Token route guard | `poetry run pytest tests/test_grafana_api_token_route.py -q` | 5 passed |
| Guard is real | `make mutate ... TEST=tests/test_grafana_api_token_route.py` (negated matcher replaced) | RED, 1 failed 4 passed, file restored |
| Routing with duplicate headers | Rule extracted from `patches.yaml`, run on `traefik:v3.6` | Bearer alone reaches the ungated service; Basic then Bearer, Bearer then Basic, lowercase basic and Basic alone reach the gated one |
| Merge of #2370 | `gh pr merge 2370 --squash --match-head-commit cb26787b...` | MERGED f7d55c62 |
| Queue | `dotf pr triage-queue` | `[OK] no reviewer output is awaiting a disposition` |

## Findings filed or open

- #2374: Loki's bearer route uses the Traefik v2 matcher `HeadersRegexp`, so it is disabled and has never routed.
- #2380: the persona task of `agent_stack` fails under `--check` (a check-mode artifact).
- Not done, by design of this window: the Grafana token wiring to the gateway, the 8-hour report job, the mail poll script, the GitHub PR workflow, the ADR-019 amendment. The next AI-024 tasks are in `specs/AI-024-hermes-reach/tasks.md`.
- A merged lesson index: lesson-585 holds the Authelia and Traefik findings.

## Budget spent

Iterations: about 6 PR cycles over roughly 2 hours of the 3-hour window. No dollar figure exists; the provider exposes none to this run.

## Host

The machine stayed awake for the whole window (CI polls ran continuously), so the window was covered.

## Next action

Merge #2373 after dismissing the GitGuardian alert, then run the live check above and start the Grafana wiring (AI-024 stage 2) in a fresh sibling worktree.
