# Run ap-20261102-kubelab-auth

**Verdict:** ended `queue-empty` after 5 items in about 2h45m (05:51Z to 08:35Z, 2026-11-02).

| Done | Parked | Merged | Unmerged |
|---|---|---|---|
| 4 | 0 | 1 | 1 |

What waits on a human:

- **Irreversible, already landed:** #2947. It merged, and AI-025 is archived inside it.
- **Waiting on a decision:**
  - #2965 is waiting on a merge.
  - #1733 is waiting on AC2.
  - #2971 is waiting on a decision.
  - ace2 needs a provision from master.

## Waiting on you

1. **#2947 landed** (`a504558`). Closes #2915, and archives AI-025 with a PASS WITH GAPS review.
   - Not live on ace2 yet: another lane provisioned ace2 from master at about 07:45Z for #2921, before this merged. The code-interpreter default and memory background review return with the next `make provision NODE=ace2 ENV=prod TAGS=agent_stack` from master.
2. **#2965, ADR-062 amendment P3** (sign-in starts at Authelia for every app reached by people).
   - State: CI green, two triage rounds posted, triage queue clear.
   - Left unmerged on purpose: it writes doctrine into an ADR, so it is yours to accept.
3. **#1733**: no code left. #2276 landed AC1, AC3 and AC4 on 2026-10-14.
   - AC2 was met differently: the default stays a dry run that names the keys it would write.
   - Accept that and close the issue, or ask for a write-by-default.
4. **#2971 (SEC-041)**: web results can become persisted memories through the background review. Three options are on the issue:
   - accept and document;
   - turn the review off;
   - look for a setting that excludes tool output.

## Parked

None.

## Done

- #2482 body: ticked Uptime Kuma phase 1, which landed in #2491 and was verified on #2483.
- Two tickets filed from the independent reviews, both on the board:
  - #2970 (AI-026): SearXNG probe, the port wired on the client side only, and a live read of the effective config.
  - #2971 (SEC-041).
- Lesson-692 (Pyodide's 60 s limit includes the package download), landed in #2947.
- Lesson renumber: #2930's lesson collided with master's 688 and became 690.

## Evidence index

| Item | Command | Result |
|---|---|---|
| #2947 | `dotf pr triage-queue --pr 2947` then `dotf pr land 2947` | `[OK]`, `[MERGED] #2947 at a504558` |
| AI-025 archive | `dotf spec archive AI-025` | `[OK] Archived`, review `nan/qwen3.8-flash` PASS WITH GAPS at `931dcf5d` |
| AI-025 tests | `pytest tests/test_open_webui_* tests/test_agent_stack_role.py tests/test_platform_manifest*.py tests/test_spec*.py` | 128 passed |
| #2965 | `dotf pr triage-queue --pr 2965` | `[OK] no reviewer output is awaiting a disposition` |
| #2915 | `gh api repos/mlorentedev/kubelab/issues/2915` | `closed` |

## Budget

- Items: 5 of 6.
- Time: about 2h45m of 12h.
- No dollar figure exists for this run.
- Reviewer quota: CodeRabbit and Codex were rate-limited on every PR, so PR-Agent and the pooled spec reviewer were the only reviews.

## Host

- Wake lock: `caffeinate -i -s -t 43200` held from 05:52Z, and the Mac was on AC power.
- No remote writes: no provision and no deploy.

## Next action

Provision ace2 from master (`make provision NODE=ace2 ENV=prod TAGS=agent_stack`) so #2947 and #2921 are both live. Then merge or amend #2965.
