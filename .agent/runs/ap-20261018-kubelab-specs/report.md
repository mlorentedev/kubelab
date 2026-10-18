# Run ap-20261018-kubelab-specs: report

**Verdict:** the run ended on time (expiry 16:35Z), after about 8 hours.

- Spec PRs merged: 5 of 8 (TOOL-035, APP-CONFIG-016, AUTH-004, CONSOLE-002, OPS-016).
- Unmerged: 2 (DT-004, TOOL-001). Both are triaged and waiting only on CI after the master fix, #2524.
- Parked: 1 (TOOL-009).
- DELIVERY-004 was out of scope by the operator's ruling.

**Active specs on master:** 20 at arming, 15 now. The count drops to 13 when #2496 and #2507 land, and to 12 with TOOL-009. The WIP limit is 10, so #2443 stays open.

## Waiting on you, irreversible first

Nothing irreversible is pending. Every merge has landed, and no prod mutation ran. The prod commands this run executed were all read-only: `auth-review`, `secrets audit`, `monitoring-apply CHECK=1` and `n8n-probe`.

1. **#2524: master is red until it lands.** `docs/lessons/_index.md` says 596 lessons, but 598 files exist. Two lesson tests fail on every PR.
   - Cause: #2489 (this run) and #2513 (a peer) each added a lesson against their own base. Git merged the shared counter line without a conflict.
   - The recurrence of the #1649 class is filed as #2525, with two options: (A) stop committing the total; (B) re-derive the count on the merge result in the land path.
   - If #2524 is not merged when you read this: CI green → triage → `dotf pr land 2524`.
2. **#2496 (DT-004) and #2507 (TOOL-001):** triaged, with `dotf pr triage-queue --pr N` clear. Their only red check is the master defect above. After #2524 merges:
   1. Merge master into each branch.
   2. Wait for CI and triage PR-Agent's re-run.
   3. Run `dotf pr land N`.

   After the merges, close #465 (pointing at #2416) and #520 (pointing at #2499 and #584).
3. **#2515 (TOOL-009), parked as a draft.** `tests/test_spec_gate.py:360` hardcodes TOOL-009 as the one cross-repo spec. `tests/` was frozen for this run.
   - (A), recommended: expect `set()` and drop TOOL-009 from the docstring, in #2515.
   - (B): keep TOOL-009 active until iris#30 lands, and close #2515.
4. **Token expiries** (read from SOPS metadata, values never printed):

   | Token | Expires |
   |---|---|
   | `github_migration_token` | 2026-10-27 |
   | `r2_token_minter` | 2026-11-03 |
   | `dev_node.github_token` | 2026-11-06 |
   | n8n `analytics_token` | not recorded in this run; `make secrets-audit ENV=prod` lists it |

## Done

| Spec | PR | Merge | Carried remainder |
|---|---|---|---|
| TOOL-035 | #2489 | `01a12a7` | #2485 (ts-bridge cutover), #2488; #1076 closed; #1389 commented |
| APP-CONFIG-016 | #2497 | `bb74d11` | #1871 closed |
| AUTH-004 | #2509 | `36e514e` | #2503, #2504, #2505; #1013 closed |
| CONSOLE-002 | #2510 | `32dd8d4` | #2494, #2501; #711 closed as superseded (ADR-066) |
| OPS-016 | #2518 | `12453fc` | #2500, #2506; #959 commented |
| DT-004 | #2496 | pending (item 2 above) | #465, then #2416 |
| TOOL-001 | #2507 | pending (item 2 above) | #2499, #584, #520 |
| TOOL-009 | #2515 | parked (item 3 above) | iris#30 |

Every archive had an independent `dotf spec review`. Each is PASS or PASS WITH GAPS, and each finding is dispositioned in its `verification.md`. Every amendment rewords an acceptance criterion and deletes none.

## Findings filed this run

| Ticket | Subject |
|---|---|
| #2494 | CONSOLE-002 AC4 |
| #2499 | `secrets audit` exits 0 on a missing key |
| #2500 | rpi3 and headscale have no port-drift recreate |
| #2501 | spec-gate guard gaps |
| #2503, #2504, #2505 | AUTH-004 remainders |
| #2506 | delete-guard test, plus the sleep check |
| #2525 | lesson count race |

Comments were also added to dotfiles#1727 (launcher base, abandoned-mode template status) and #2506.

## Evidence

- Logs in this directory: `auth-review-prod.log`, `secrets-audit-prod.log` (key paths only), `monitoring-check.log`, `n8n-probe-prod.log`.
- `make monitoring-apply CHECK=1`, re-run at 11:45Z: `0 create, 0 edit, 0 delete (live=36, seed=36)`.
- Tests per PR are in each PR body.
- The ledger is `ledger.md`.

## Budget and host

- Started 08:35Z; expires 16:35Z.
- No breaker tripped. The only park is TOOL-009, and it is a scope park, not a fix loop.
- The host was kept awake with `caffeinate -i`.
- Reviewers: PR-Agent was the only one that reviewed. CodeRabbit and Codex were rate limited for the whole run.

## Next action

Land #2524 (if it is still open), then #2496 and #2507. Then answer #2515 A or B.
