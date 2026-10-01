---
spec: "BACKUP-068-app-restore-drill"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "416ab9913a3aa05c158d5728d769e1e6cdf7b732"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: BACKUP-068-app-restore-drill — the Authelia and n8n restore drill (`make backup-drill-apps ENV=prod`).
**Sources**: `specs/BACKUP-068-app-restore-drill/{proposal,tasks,verification}.md`, `features.json`; diff `335da3b1bbe9e70619cb819c707397ef7d0b4471...HEAD` (`git rev-parse HEAD` = `416ab991`); the spec's own commit is `6259d41e` (parent `335da3b1`), the rest of the diff is master's later merges (#2000–#2009).

### Evidence reproduced in this session

Run from the worktree, with the worktree's own `toolkit/` forced onto `sys.path` (the worktree's `.venv` is not provisioned — no `pytest_cov`, no `toolkit` metadata — so the complete venv at `../kubelab/.venv`, itself at the same `416ab991`, supplied the interpreter; `PYTHONPATH` picked this worktree's source, confirmed by importing `app_drill.__file__`):

- `pytest -q --no-cov tests/test_app_drill.py` → **41 passed** (41 collected).
- Whole unit suite at `416ab991` (`pytest -q --no-cov --ignore=tests/test_app_drill.py`) → **3358 passed, 16 skipped, 2 xfailed, rc 0** (154 deselected by the repo's marker filter). With the focused file, 3399 passed.
- Mutation edits to `toolkit/features/app_drill.py`, each reverted with `git checkout` (tree clean afterwards): `--network none`→`bridge` (2 failed), key mode `0600`→`0644` (2 failed), teardown result ignored (`return ok`) (2 failed), identity-digest comparison disabled (2 failed), encryption-check text ignored (1 failed), `sqlite_intact` guard disabled (1 failed). **Six of six mutations killed**; three overlap the author's own table, three were chosen fresh.
- `dotf spec archive BACKUP-068-app-restore-drill` run against a scratch copy of the spec (`/tmp/specgate`), not this tree: **refused** (see finding 1).
- Contract files untouched by me; `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` absent; `nan/deepseek-v4-flash` is the pool's `primary` in `harness/reviewer-pool.json`.

### Spec and task alignment

- AC1–AC5 each have a named test or a prod transcript, and I re-derived the mapping: AC1 (`test_authelia_reads_the_encryption_check_text_because_it_exits_0_on_failure`, `test_a_rotated_opaque_identifier_fails_and_never_starts_a_server`, `test_a_server_that_never_answers_healthy_fails[authelia]`), AC2 (`test_a_workflow_missing_from_the_restore_fails_and_is_named`, `test_n8n_names_a_key_that_is_not_the_datas`, `test_n8n_fails_when_a_credential_does_not_decrypt`, the five CANNOT CHECK cases), AC3 (`test_the_key_travels_only_as_a_private_file_into_a_container_with_no_network`, `test_a_complete_restore_that_leaves_its_container_behind_fails`, `test_a_complete_restore_that_leaves_the_data_on_disk_fails`), AC4 (`test_the_drill_reads_the_files_keys_and_target_the_ssot_declares` + two prod transcripts), AC5 (runbook section).
- `tasks.md` boxes are all `[x]` and each maps to diff evidence; the one open box is the review itself. No `[x]` is unsupported.
- The out-of-scope list (no live cut-over, no transient tables, no app CLI in-pod, no scheduling) matches the code: the drill never scales or writes to the cluster, compares only `APPS[*].tables`, and reads live with `sudo -n sqlite3 -readonly` over SSH.
- The spec's own commit `6259d41e` touches exactly the files the proposal implies (drill, CLI command, Makefile target, `ENV_TARGETS` regression row, tests, runbook, lesson, and the `headscale_drill` helper exports it imports). The remaining files in the launcher's diff are master merges #2000–#2009, not this change; I checked the only interaction that could reach it — the #2004/#2009 host-client barrier in `tests/conftest.py` denies `kubectl`/`ssh`/`restic`, and the app-drill suite passes with the barrier active at HEAD.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor (archive-blocking) | REAL | spec artifact / archive gate | `verification.md`'s "Promotion candidates" cannot be read by the archive pre-flight: two candidate lines have no `?`, so the parser treats the whole line as the question and the answer as empty. `dotf spec archive BACKUP-068-app-restore-drill` refuses, for all three pre-flights' worth of value. | Reproduced against a scratch copy with the installed CLI: `Error: promotion candidates in verification.md are not all answered: Lesson: `docs/lessons/storage-backup/lesson-500-….md`.? unanswered … Debt found: #1998 …, #1997 ….? unanswered …; no flag skips this check`. Matches `cli/internal/spec/promotion.go` (`strings.Cut(m[1], "?")` then `promotionAnswer`) in the dotfiles repo. | UNTESTED (no repo test asserts the spec's own verification.md answers its promotion lines) | spec artifacts — `verification.md` **is outside the contract set**, so answering the two lines does not stale this review |
| Minor | REAL | verification | The recorded test-status evidence is unreproducible at `reviewed_sha`: `verification.md` claims `tests/test_app_drill.py` → 39 passed (the file collects and passes 41 at HEAD), and pins `make test` to `33e2859f`, which is a pre-squash branch commit, **not** an ancestor of HEAD. The substance is fine — I reproduced both — but as written the numbers cannot be re-run as claimed. | `41 passed in 1.53s`; `--collect-only` → 41; `git merge-base --is-ancestor 33e2859f HEAD` → false (`33e2859f` is `docs(backup): … the runbook, and lesson-500`, 10:46, squashed into `6259d41e`) | the focused suite itself (green; the defect is the recorded count/sha, not the behaviour) | spec artifacts — `verification.md` |
| Minor | THEORETICAL | correctness / completeness rule | The "newer by id" rule for tables without a timestamp can read a genuinely lost **trailing** row as newer-than-snapshot and pass. With live `{1..5}` and a restore truncated to `{1..4}`, row 5 is `highest=None`-safe only because the restore is empty — with a non-empty restore it is `INFO … newer than the snapshot` and the drill returns True. A restore of an older snapshot has the same shape: every live row above the restored maximum becomes INFO. | Code read: `compare()`, `elif created is None and key.isdigit() and highest is not None and int(key) > highest`. The inverse (empty restore never excuses) is guarded and tested; this direction is not. No reproduction on real data — `restic restore` plus `integrity_check` make truncation unlikely. | UNTESTED (no test covers a missing row whose id is above the restore's highest) | code + tests (or a line in `proposal.md` bounding the heuristic) — `tasks.md`/`proposal.md` edits would stale this review, `verification.md` would not |
| Minor | THEORETICAL | resilience | Two inputs are parsed without a CANNOT CHECK path: `json.loads(out or "[]")` for `restic snapshots --json` when rc is 0 but the output is malformed, and `spec["sqlite"]` / `spec["pvc"]` in `drill_apps` when the SSOT entry lacks the key. Both raise out of the drill (a traceback and a non-zero exit) instead of naming what could not be read, unlike every other unreadable input in the same function. | Code read of `run_drill` and `drill_apps`; the live read and the image read both have explicit `CANNOT CHECK` branches beside these. | UNTESTED | code |
| Minor | REAL | maintainability | `run_drill` is 104 lines with ~26 decision points and `_prove_authelia` 76, over the repo's `<40 lines` / `CC < 10` rule in `AGENTS.md`. Nothing enforces it: `pyproject.toml` selects `["E","W","F","I","B"]` (no `C901`, no length check), so pre-commit is green regardless. | AST measurement of `toolkit/features/app_drill.py`; `[tool.ruff.lint].select` in `pyproject.toml`. Note the sisters share the shape (`headscale_drill._restore_and_check` 108, `gitea` 103, `postgres.run_drill` 49), so this is a repo-wide pattern, not a new deviation. | the existing behavioural tests (shape is untested by construction) | code (extract the restore/compare/prove phases) or vault (a pattern note if the sisters are to be brought back under the bar) |

Severity rationale for finding 1: the product behaviour is correct and the fix is two lines in a file the archive's staleness check does not digest, but the consequence is a hard refusal at `dotf spec archive` — the tool prints exactly what to write and "no flag skips this check". That is process friction with no risk of a wrong archive, so I keep it Minor; it must still be dispositioned before archiving.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | AC1–AC5 hold on the evidence I could reproduce (focused suite, six independent mutations killed, disabled-guard red-green, prod transcripts); the completeness heuristic has one untested bound (finding 3) and the credential-decrypt **failure** branch was never observed on real data, as `verification.md` itself discloses. |
| Verification       | B | Real prod transcripts, a 17-row mutation table and named tests per criterion — but the recorded counts/sha are stale (finding 2) and the promotion section blocks its own archive (finding 1). |
| Scope              | A | The spec's own commit `6259d41e` matches the proposal file-for-file; the extra files in the launcher's diff are master merges #2000–#2009, separately reviewed, and the one interaction that reaches this change (the host-client barrier) was tested green here. |
| Reliability        | B | Teardown is on every exit path and read back; every unreadable input has a CANNOT CHECK branch — except the two parses in finding 4. |
| Maintainability    | B | Clear names and WHY-comments, typed, no dead code, complex logic isolated in small helpers (`compare`, `rows_sql`, `parse_rows`); the two long functions (finding 5) and the untested parse paths keep it from A. |
| Handoff-readiness  | B | lesson-500 written, runbook section with both the drill and the real restore, debt ticketed (#1997/#1998), promotion paths exist on disk — but the promotion section's format makes the archive pre-flight refuse (finding 1). |

Aggregation: no D and no C → **PASS** by the rubric; findings are minors only, one with an archive-blocking consequence, so the verdict is issued as PASS WITH GAPS to keep the open item tracked rather than waved through.

### Verdict

**PASS WITH GAPS**

No code defect found: the change does what the proposal says, the guards are real (six mutations, each killing a named test), and the secrets discipline holds (no key on argv or in `-e`, `0600` key file in a `0700` tree, only ids and counts printed, container and directory read back as removed). Both open items are in `verification.md`, which is outside the contract set: fixing them does not invalidate this review, and no re-review is needed.

`dotf spec archive BACKUP-068-app-restore-drill` is **not advisable yet** — it will refuse on the promotion pre-flight (finding 1) even with this review in place. Answer the two lines first; then archive.

### Recommended next steps

Each of these is outside the contract set (`proposal.md`, `tasks.md`, `features.json`), so applying them keeps this review fresh. Record the disposition in `verification.md` — applied, ticketed, or declined with a reason.

1. **[must fix before archive]** In `verification.md`, give every "Promotion candidates" line a `?` and an answer the parser can read: `yes: <path>` naming files that exist, or `no: <reason>`. Concretely, the lesson line becomes e.g. `- [x] Lesson captured? yes: docs/lessons/storage-backup/lesson-500-n8n-cli-answers-nothing-at-log-level-warn.md` and the debt line e.g. `- [x] Debt ticketed rather than promoted? no: #1998 and #1997 are on the board`. Verify with `dotf spec archive BACKUP-068-app-restore-drill` (dry inspection: it should move past the promotion error before the review gate).
2. Correct `verification.md`'s test counts: `tests/test_app_drill.py` → 41 passed at `416ab991`; drop or re-run the `make test` line pinned to the non-ancestor `33e2859f` (whole unit suite at `416ab991`: 3358 passed alongside the focused 41, rc 0).
3. [ticket] Bound finding 3: add a `compare()` test where a live row without a timestamp is missing from a non-empty restore and its id is above the restore's highest but the row is knowably old — or state in the spec that trailing-row loss is outside the heuristic. Same PR as any follow-up to the sister drills, if the shared shape is addressed (finding 5).
4. [ticket] Give the two parses in finding 4 a `CANNOT CHECK` branch, as their neighbours already have.
5. [optional, repo-wide] Extract the phases of `run_drill` if the drill family is to come back under the `<40 lines` / `CC < 10` bar; as noted, all four drills exceed it today, so this is a pattern decision, not a BACKUP-068 defect.
