---
spec: "BACKUP-040-gitea-restore-drill"
verdict: "FAIL"
reviewed_sha: "8033834e02c05ffe05a2d63a6a9ff377106c42d7"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: `BACKUP-040-gitea-restore-drill` — the Gitea restore drill and the pieces it directly needs
(`toolkit/features/gitea_drill.py`, `gitea_client.list_branches`/`commit_exists`, `toolkit/cli/backup.py`
`drill-gitea`, `Makefile` target, `docs/runbooks/offsite-backup-restore.md` §Gitea, lesson-499,
`tests/test_gitea_drill.py`, `tests/test_gitea_client_pagination.py`).
**Sources**: `specs/BACKUP-040-gitea-restore-drill/{proposal,tasks,verification}.md`, `features.json`,
`git diff 5cf698779b20e93a2d9501d27a8cedfe2711ccb2...HEAD`, `git log 5cf698779b20e93a2d9501d27a8cedfe2711ccb2..HEAD`.
The launcher's base is far enough back that the range also carries peer specs (BACKUP-046/063/067/068/070/071,
crowdsec WAL, lessons-index ordering, the host-client barrier). Those were read for interaction only; the
findings below are against BACKUP-040's change.

### Spec and task alignment

- AC1 (restore + `git fsck --full` per repo, names the failure): code at `gitea_drill.py:_restore_and_check`
  and `repos_on_disk`; covered by `test_a_corrupt_repository_fails_names_it_and_never_starts_a_server`.
- AC2 (pinned image, `--network none`, API lists live's repos, no emptied repo, every restored head known):
  covered by `test_the_restored_server_has_no_network_and_runs_the_pinned_image`,
  `test_an_incomplete_restore_fails_and_names_the_repository` (4 params), `test_a_repository_empty_in_both_is_not_a_failure`.
- AC3 (CANNOT CHECK on unreadable/empty live, and on no readable snapshot): live cases covered by
  `test_live_that_cannot_be_read_or_lists_nothing_is_cannot_check`; **the no-snapshot case is not** (Finding 2).
- AC4 (nothing left behind on every exit path): teardown is exercised by every run test via `_torn_down`,
  but the guard that turns a *failed* teardown into a failed drill is not covered (Finding 1).
- AC5 (runbook + measured RTO): met; runbook §Gitea documents both the drill and the real restore, and
  `verification.md` records the workstation and ace2 transcripts and the 17 s/22 s RTO.
- `tasks.md` closing item (`Independent adversarial review, then archive`) is the only unticked box and is
  consistent with this run. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in the spec files.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | teardown / AC4 | The drill's "a restore that passed but left the forge's copy behind is not a pass" guard (`return ok and removed and wiped`) is enforced by no test. Removing it (`return ok`) leaves the whole gitea suite green, so a regression that leaves a full copy of the private forge — `gitea.db` password hashes, `app.ini` secrets, SSH host keys — on disk would still report success. The sibling drill tests exactly this twice. | Mutation M2 on the committed tree: `toolkit/features/gitea_drill.py` `return ok and removed and wiped` → `return ok`; `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_gitea_drill.py` → **19 passed** (guard survives). Contrast `tests/test_postgres_drill.py::test_a_complete_restore_that_leaves_its_data_behind_fails` and `::test_a_container_left_behind_fails_even_without_a_volume`. `verification.md`'s mutation table lists 7 guards; this one is not among them. | UNTESTED | tests (port the two postgres tests to `tests/test_gitea_drill.py`) |
| Major | REAL | error path / AC3 | AC3 names "no snapshot is readable" as a CANNOT CHECK case, but that branch is exercised by no test, and it is the only CANNOT CHECK case whose message does not carry the `CANNOT CHECK` class. The sibling Headscale drill prints `CANNOT CHECK — no snapshot readable in …` and has a named test asserting the word. | Mutation M4: `if not snapshots:` → `if snapshots is None:` (branch unreachable), `pytest tests/test_gitea_drill.py` → **19 passed**. Code read: `gitea_drill.py` logs `drill: no snapshot readable in {repo}` vs `headscale_drill.py` `drill: CANNOT CHECK — no snapshot readable in {repo}` (`tests/test_headscale_drill.py::test_no_readable_snapshot_is_cannot_check`). | UNTESTED | code (align the message with AC3/headscale) + tests (`test_no_readable_snapshot_is_cannot_check`, mirroring headscale's) |
| Minor | THEORETICAL | robustness | `gitea_drill._paginate` handles a top-level `null` page but not a non-list body under a key: `{"data": null}` or a dict body raises `TypeError`, and a string body raises `TypeError`, escaping `_restore_and_check` as a traceback instead of the AC2/AC3 contract "a failed read of the restored server is CANNOT CHECK". The client counterpart deliberately raises a handled error for the same input. Fails closed (exit 1, teardown still runs), so it is not a false pass. | Reproduced against the committed function: `_paginate(lambda p: {"data": None}, "/repos/search", key="data")` → `TypeError: 'NoneType' object is not iterable`; `{"data": {"a": 1}}` → `['a']` (silently wrong); `"oops"` → `TypeError: string indices must be integers`. Compare `GiteaClient._paginate`'s `if not isinstance(items, list): raise GiteaError(...)`. | UNTESTED | code (`return None` on a non-list body) + tests |
| Minor | THEORETICAL | correctness | A repository renamed or moved between the snapshot and the run is a **false failure**: live lists the new `owner/name`, `on_disk` and `restored` hold the old one, so the drill reports `FAIL <new>: missing from the restored repositories` and exits 1 on a perfectly good restore. The "complete, never equal" contract tolerates drift in branch counts but not in names; renames are not covered by any test. | Code read: `compare()` `if repo.lower() not in on_disk` / `if repo not in restored`, keyed on live's names; no rename mapping and no test. Not observed on prod (5 repos unchanged). | UNTESTED | tests (pin the rename case) + possibly code (report distinct from "missing") |
| Minor | THEORETICAL | correctness | A repository present in the restored database but absent on disk is never checked when live no longer lists it: `compare()` reports it as `restored, gone from live since the snapshot` and passes, and `git fsck` only visits what `repos_on_disk` found. The drill can therefore pass over a restored forge whose DB references a repository with no directory. AC2 scopes the disk check to live's repositories, so this is a gap in "whole", not a stated-AC violation. | Code read: the final loop `for repo in sorted(set(restored) - set(live))` emits an informational line and continues. | UNTESTED | tests + code (or accept as a documented limit of "complete") |
| Minor | REAL | maintainability | `_restore_and_check` is 103 lines with an estimated cyclomatic complexity of ~16 (AST decision-node count), and `run_drill` is 65 lines at ~11. The repo's own bar is <40 lines and CC<10 (`AGENTS.md`, `pattern-language-standards`), and ruff carries no complexity rule here, so nothing gates it. | Measured this session with an AST pass over `toolkit/features/gitea_drill.py`; `poetry run ruff check` is clean (no mccabe configured). | n/a (structural) | code (split restore / fsck / server-start / token / compare into helpers) |
| Question | — | spec artifacts | All three `features.json` entries are `state: "pending"` with empty `evidence`, while `verification.md` records passing prod runs and the `tasks.md` closing item claims "features.json verifications non-vacuous". The `/spec` SKILL states `state`/`evidence` are harness-filled, so this may resolve at archive time — but every archived sibling carries `passing` + evidence text. Confirm the archive tooling fills them rather than archiving a contract file that records nothing. | `specs/BACKUP-040-gitea-restore-drill/features.json` vs `specs/archive/BACKUP-068-app-restore-drill/features.json`. | n/a | spec artifacts (or state that the harness owns it) |

No Blocker was found: the drill fails closed on every path I could exercise, the restore never touches
live, live is read with `read:repository`, the scratch server has no network and is reached by
`docker exec` only, and the token and `app.ini` are asserted absent from output.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | AC1/AC2/AC5 verified with prod + ace2 transcripts, but two AC-named negative paths are unexercised and two unhandled drift cases (rename, DB-only repo) are unpinned. |
| Verification       | B | Strong reproducible evidence (two prod transcripts, docker read-back for teardown and volumes, RTO) — but the mutation table is incomplete (two guards survive), and I could not complete a full-suite run in the window. |
| Scope              | B | The BACKUP-040 files match the proposal exactly; the reviewed range additionally carries six peer specs, so the diff is not BACKUP-040 alone. |
| Reliability        | B | Teardown is unconditional with read-back from docker, and the drill fails closed; a malformed page body still escapes as a traceback instead of CANNOT CHECK. |
| Maintainability    | C | `_restore_and_check` 103 lines / CC ~16 and `run_drill` 65 lines / CC ~11 exceed the repo's own <40 / <10 bar, and no linter gates complexity. |
| Handoff-readiness  | A | Runbook §Gitea covers the drill and the real restore, lesson-499 is written and indexed, `verification.md` carries transcripts, RTO and decisions. |

### Verdict

FAIL — two **REAL Major** gaps (the unenforced leftover/failed-teardown guard, and AC3's untested,
mis-labelled no-snapshot branch) plus a Maintainability **C**. The implementation is sound; the gate is
failing on the evidence that would have to hold when someone later edits this drill.

### Recommended next steps

- **(tests)** Add `test_a_complete_restore_that_leaves_its_data_behind_fails` and
  `test_a_container_left_behind_fails_even_without_a_volume` to `tests/test_gitea_drill.py`, ported from
  `tests/test_postgres_drill.py`. This is the minimum that flips Finding 1.
- **(code + tests)** Give the no-snapshot branch the `CANNOT CHECK` wording that AC3 and
  `headscale_drill.py` use, and add `test_no_readable_snapshot_is_cannot_check` (mirroring
  `tests/test_headscale_drill.py`). This is the minimum that flips Finding 2.
- **(tests, then code if it changes)** Pin the rename and DB-only-repository cases as documented
  behaviour — a passed drill with an explicit "renamed live, not a failure" line, or a named failure.
- **(code)** Split `_restore_and_check` into restore / fsck / server-start / token / compare helpers, and
  make `_paginate` return `None` on a non-list body.
- **(spec artifacts)** Decide whether `features.json` `state`/`evidence` are harness-filled; if so, say
  so at archive time rather than archiving them pending and empty.
- **(process)** This spec's portion of the diff exceeds the ~300-LOC atomic-PR cap (`AGENTS.md` §Discipline
  Gate); the spec itself is the escalation the rule asks for, so this is recorded, not actioned.
- After the fixes to findings 1 and 2, re-run this review (the verdict is FAIL, so a fresh review is
  required before archive). `dotf spec archive` is **not** advisable at this commit.

### Evidence run in this session

- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_gitea_drill.py tests/test_gitea_client_pagination.py tests/test_postgres_drill.py` → **40 passed**.
- `features.json` f3 command (`… test_gitea_drill.py test_postgres_drill.py -k 'torn_down or …'`) → **6 passed, 31 deselected**.
- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_make_env_default_is_reachable.py` → **81 passed**.
- `poetry run ruff check toolkit/features/gitea_drill.py tests/test_gitea_drill.py` → **All checks passed**.
- Mutations on the committed tree, each reverted with `cp` from a saved copy (working tree verified clean
  afterwards): M1 on-disk guard → 1 failed (killed); M2 leftover guard → 19 passed (**survives**);
  M3 `null`-page fix reverted → 1 failed (killed); M4 no-snapshot branch → 19 passed (**survives**).
- Full-suite run (`pytest -q … tests/`, the equivalent of the `make test` claim in `verification.md`,
  which reports 3484 passed at `4d995e69`): **UNVERIFIED** — the run reached 60% in the time budget and
  stalled in `tests/test_monitoring_integration.py` (an infra-marked, non-diff file, not reachable from
  this workstation). The claim is plausible but was not reproduced here.
