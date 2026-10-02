---
spec: "BACKUP-040-gitea-restore-drill"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "dbdbfc88ac84d09ea8d029e5476e9bcc408e5d46"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: `BACKUP-040-gitea-restore-drill` — the Gitea restore drill and the pieces it directly needs
(`toolkit/features/gitea_drill.py`, `gitea_client.list_branches`/`commit_exists`, `toolkit/cli/backup.py`
`drill-gitea`, the `Makefile` target, `docs/runbooks/offsite-backup-restore.md` §Gitea, lesson-499,
`tests/test_gitea_drill.py`, `tests/test_gitea_client_pagination.py`).
**Sources**: `specs/BACKUP-040-gitea-restore-drill/{proposal,tasks,verification}.md`, `features.json`,
`review-request.json`, `git diff 5cf698779b20e93a2d9501d27a8cedfe2711ccb2...HEAD`,
`git log 5cf698779b20e93a2d9501d27a8cedfe2711ccb2..HEAD`.

The launcher's base is far enough back that the range also carries peer specs (BACKUP-046/063/067/068/070/071,
crowdsec WAL, lessons-index ordering, the host-client barrier). Those were read for interaction only — the
`remove_scratch_container` seam, the ace2 remote-run path, the capture template — and the findings below are
against BACKUP-040's change. This round reviews the whole change, not the delta since round 2.

### Spec and task alignment

- AC1 (restore + `git fsck --full` per repository, names the failure): `gitea_drill.py:repos_on_disk` +
  the `broken` comprehension; `test_a_corrupt_repository_fails_names_it_and_never_starts_a_server`.
- AC2 (pinned image, `--network none`, API lists live's repositories, no emptied repository, every restored
  head known): `test_the_restored_server_has_no_network_and_runs_the_pinned_image`,
  `test_an_incomplete_restore_fails_and_names_the_repository` (4 params),
  `test_a_repository_empty_in_both_is_not_a_failure`, `test_a_restored_head_live_does_not_know_fails`.
- AC3 (CANNOT CHECK, never a pass, when live cannot be read or lists nothing, and when no snapshot is
  readable): live-unreadable/empty is `test_live_that_cannot_be_read_or_lists_nothing_is_cannot_check`;
  no-snapshot is now `test_no_readable_snapshot_is_cannot_check` (restic-fails / empty / malformed), and the
  message carries the `CANNOT CHECK` class. Both round-2 Majors' paths are now named tests.
- AC4 (container, volumes, directory gone on every exit path; tests pin it): teardown is in an unconditional
  `finally`; the guard `return ok and removed and wiped` is now covered by
  `test_a_complete_restore_whose_container_is_left_behind_fails` and
  `test_a_complete_restore_that_leaves_its_data_on_disk_fails`, and every other run test asserts
  `_torn_down`. The volume read-back itself is not exercised by the Gitea fake (a bind mount lists none), but
  the shared helper is covered by `tests/test_postgres_drill.py::test_a_container_left_behind_fails_even_without_a_volume`.
- AC5 (runbook + measured RTO): `docs/runbooks/offsite-backup-restore.md` §Gitea documents the drill and the
  real restore (`restic restore --include /opt/node-backup/staging/gitea`, stop/move/start, `1000:1000` owner
  check, keep `data.broken-*`); lesson-499 exists and is indexed in `docs/lessons/storage-backup/_index.md`;
  `verification.md` carries the workstation and ace2 transcripts and the 17 s / 22 s RTO.
- `tasks.md` closing item (`Independent adversarial review, then archive`) is the only unticked box and is
  consistent with this run. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in `proposal.md`,
  `tasks.md` or `verification.md`.
- `features.json` now records `state: passing` with non-empty evidence for all three features — the round-2
  open Question is resolved. (`review-request.json`'s `contract_digests` were taken as given; there is no
  digest tooling in this repo to recompute them, so they are UNVERIFIED here.)

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | tests / AC1 | The `if rc != 0 or not data.is_dir():` early return in `_restore_and_check` — the "restic could not restore" path every run depends on — has no named test. Making the branch unreachable (`if False:`) leaves the whole Gitea suite green. It fails closed even when broken: with the guard gone, `on_disk` is empty and `compare` reports every live repository missing, so this is message-quality risk, not a false pass. | Mutation on the committed tree: `if rc != 0 or not data.is_dir():` → `if False:`; `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_gitea_drill.py` → **31 passed**. A hand-written case returning `rc=1, "Fatal: unable to restore"` from the restore call yields the intended `drill: restic could not restore …` and `False` on the current code. | UNTESTED | tests (one case whose restore call returns rc=1) |
| Minor | REAL | maintainability | `_restore_and_check` is 103 lines at an AST decision-node count of ~17; `run_drill` 68 lines at ~14; `compare` 39 lines at ~11. The repo's bar is <40 lines and CC<10, and ruff carries no mccabe rule, so nothing gates it. Carried debt, not a regression of this change. | This session: AST pass over `toolkit/features/gitea_drill.py` (counts `if/while/for/try/except/BoolOp/IfExp/comprehension`); `poetry run ruff check toolkit/features/gitea_drill.py toolkit/features/gitea_client.py tests/test_gitea_drill.py` → "All checks passed!". Tracking ticket confirmed open and scoped: `gh issue view 2015` → `{"state":"OPEN","title":"BACKUP-072: app drill review follow-ups (trailing-row heuristic, two unguarded parses, drill complexity)"}`. | n/a (structural) | code (split into restore / fsck / server-start / token / compare helpers — tracked by #2015) |
| Minor | THEORETICAL | resilience | Gitea reads `snapshots[-1]` where the sibling Postgres drill reads `snapshots[0]`, both after `restic snapshots --json --latest 1`. Restic's `--latest n` selects the last `n` snapshots **per host and path**, so if a node's repository ever holds two path groups the two drills pick different snapshots, and the Gitea one can select one that does not contain the staged Gitea subtree — a false FAIL caught by the `data.is_dir()` guard, never a false pass. Today one snapshot per run holds every source: the capture stages all sources under one directory and ships that. | Code read (`gitea_drill.py`, `postgres_drill.py`); restic's own help confirms the grouping: `restic snapshots --help` → `--latest n  only show the last n snapshots for each host and path`; `infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2` stages into `STAGING` and ships from it. Not observed on either prod run. | UNTESTED | code (align the two drills on one expression) — surface only; do not gate |
| Minor | REAL | correctness (accepted) | Round-2 limits re-checked: a repository renamed since the snapshot is a false FAIL under its new name, and a repository in the restored database but gone from live and from disk is not fsck'd. Both are now stated in the module docstring. | `gitea_drill.py` module docstring, "Two limits follow from checking against live…"; `compare`'s final informational loop. | n/a | spec/comment (documented limit) — accepted, no re-review |

No Blocker was found. The drill fails closed on every path exercised; it never writes to live (live is read
with `read:repository`, the token is minted inside the scratch container); the scratch server runs with
`--network none` and is reached only through `docker exec`; `repo_url()` builds `s3:{endpoint}/{bucket}/{node}`
with no credentials embedded, so the repository URL on the error paths is not a secret; and the test asserts
both the scratch token and `app.ini` never reach the output. The four mutations I ran (teardown guard,
`CANNOT CHECK` label, non-list page, `_wipe` never reporting failure) each turn named tests red — the round-2
Majors and Minor are genuinely fixed and enforced, not merely asserted in `verification.md`.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|-----------------------|
| Correctness        | B | All five criteria met and the negative paths are now pinned; one early-return branch (restore failure) has no named test and two drift cases are accepted limits. |
| Verification       | B | Two prod transcripts, docker read-back, an RTO, and a mutation table I reproduced four entries of; I reproduced the full suite on this sha (`poetry run pytest -q -p no:cacheprovider --no-cov` → 3496 passed, 16 skipped, 154 deselected, 2 xfailed, rc 0) but cannot independently re-run the prod drill, which needs R2 and SOPS. |
| Scope              | B | The BACKUP-040 files match the proposal exactly; the reviewed range additionally carries six peer specs, so the diff is not BACKUP-040 alone. |
| Reliability        | B | Teardown is unconditional, read back from docker, fails the drill when it leaves the forge's copy behind, and is now tested on both leftover paths. |
| Maintainability    | C | Three functions exceed the repo's <40-line/CC<10 bar (`_restore_and_check` 103/~17, `run_drill` 68/~14, `compare` 39/~11) and nothing in CI gates it; tracked by open #2015. |
| Handoff-readiness  | A | Runbook section, lesson-499 (written and indexed), measured RTO, `features.json` populated, and round-2 dispositions recorded with their mutations. |

### Verdict
PASS WITH GAPS

### Recommended next steps

- **Tests set** (no contract edit — apply and record in `verification.md`): add one named case to
  `tests/test_gitea_drill.py` whose restore call returns `rc=1`, asserting the `restic could not restore`
  message and the teardown; that closes the only UNTESTED finding.
- **Code set**: fold `_restore_and_check` / `run_drill` / `compare` under the complexity bar when #2015 is
  worked; align the two drills on one snapshot-selection expression (`snapshots[-1]` vs `snapshots[0]`) in the
  same pass.
- **No contract-set change is needed**: `proposal.md`, `tasks.md` and `features.json` are accurate as they
  stand, so this verdict remains valid for the archive if nothing in those three changes. The archive
  checklist in `verification.md` (status, folder move, board close, promotions) is the remaining work.
- `dotf spec archive` is **advisable** in the current state: the round-2 blockers are fixed and enforced, and
  every open finding here is a Minor that is either tracked (#2015) or recordable as a disposition.
