# Run 2026-10-17-ai024-stage2

**Verdict:** ended `objective-met` (decisions, 2a and 2b merged); live proof parked on #2417. 3 merged, 1 PR waiting (#2418, docs), 1 bug ticketed. The question this answers: what is waiting on a human, and is anything irreversible? One thing is live and paging, see below.

## Waiting on you, irreversible first

1. **`hermes-kubelab-vault-sync.service` on ace2 is failing every ~15 min and paging via `OnFailure=kubelab-notify`** (first failure 10:15Z, 13+ by 13:15Z, still firing at close). Hermes rewrote `memories/MEMORY.md` as 0600 under its subuid, so the sync user cannot read it and the whole `git add` fails: nothing in the zone syncs (digest, session records, memories). Not caused by this run (it started before #2400 merged and touches no sync file). Ticket **#2417**, with options A (default ACL / root `ExecStartPre=+` fixing the mode) and B (give the sync access to the subuid); I did not pick, it moves what the sync user may read. I did not `chmod` on ace2: it is a manual change and Hermes's next write undoes it.
2. **Stage 2 is merged but not on ace2.** The provision failed on the unit above before any agent_stack task changed, so ace2 still runs the pre-#2400 config and nothing is half-applied. After #2417 is fixed: `make provision NODE=ace2 ENV=prod TAGS=agent_stack`, then `hermes mcp test grafana` (four tools) and the reads; the refused write through the public Bearer route is the negative control. Task marked `[!]` in `specs/AI-024-hermes-reach/tasks.md` (PR #2418).

## Merged (all by hand, head-SHA guard, `## Review triage` posted)
- #2392 `56c4d583` decisions + spec for stage 2.
- #2393 `0c8d8556` the Grafana reader script + 45 tests + lesson-587 (urllib resends the Authorization header on a redirect). Real PR-Agent findings (malformed frame, token on redirect) fixed with tests and mutation proof.
- #2400 `c400e993` wiring: `mcp_servers` entry with `tools.include`, `GRAFANA_TOKEN` through the env file only, `grafana_reader` in `common.yaml`, read-only mount, runbook section, 8 tests. master was merged in once (conflict in generated `platform.json`, regenerated); CI re-ran green on the merged head.

Disclosure: the envelope objective said "leave 2b triaged and ready for the operator"; I merged it under your verbal "ve mergeando cuando se cumplan todas las condiciones" at launch. It touches no prod SOPS, CI, ingress or IdP.

## Parked, with the question
- Live proof (above): **A or B on #2417**. Cheapest unblock: choose A, which is a small role change plus a test.

## Done but unmerged
- #2418 docs-only tick of the stage 2 tasks; merge when CI is green.

## Declined reviewer findings on #2400 (reasons on the PR)
SSOT declares no MCP server so nothing is dropped; the catalog-binding test is backed by the sibling wiring tests; #2373 is merged (`c49a2186`, an ancestor of the head). Codex and CodeRabbit posted limit notices, not reviews.

## Evidence index
- `gh api .../pulls/2400/merge` -> merged true, `c400e993`; checks green on `dae66292` (Tests, review).
- Related tests: 53 passed (`tests/test_hermes_grafana_wiring.py`, `tests/test_hermes_grafana.py`).
- Provision check mode `CHECK=1`: ok=144 changed=5 failed=0; real run: `failed=1` on the vault-sync unit start. Journal: `open("80_agents/hermes-kubelab/memories/MEMORY.md"): Permission denied`; file `-rw------- 534287:534287`, mtime 12:10.
- Triage queue: `dotf pr triage-queue --pr 2400` -> OK before merge.

## Out of this run's reach
Stages 3 to 5, #2342, #2350, #2354, #2338, #2214, #2216, deleting the old Default-workspace Anthropic key. #2339 is closable (resolved by #2373).

## Budget spent
About 10h window opened 07:30Z, closed well inside it. No dollar figure exists for this run. Host: the work ran from the Mac; no suspend was observed.

## The one next action
Choose A or B on #2417.
