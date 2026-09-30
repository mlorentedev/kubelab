---
spec: "BACKUP-058-no-silent-reinit"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "4660c854e62db8620080a39085806fdf90cc478a"
reviewer: "nan/deepseek-v4-flash"
date: "2026-09-30"
---

## Adversarial review

**Scope**: BACKUP-058-no-silent-reinit, whole change (`git diff 49eac7f18f8e49fe27a7eaa8a9455b32b74fbb9f...HEAD`, 24 files, +1168/-31), on top of the launcher-resolved base `49eac7f1`.
**Sources**: `specs/BACKUP-058-no-silent-reinit/{proposal,tasks,verification,features}.md`; the diff over `infra/ansible/roles/node_backup/`, `infra/ansible/playbooks/backup-repo-reinit.yml`, `infra/k8s/base/services/r2-backup-watcher/`, `toolkit/features/backup_destination.py`, `infra/config/values/common.yaml`, `Makefile`, `tests/`, `docs/`.

### What I verified by running (not by reading)

| Check | Command | Result |
|---|---|---|
| Focused suite | `poetry run pytest tests/test_node_backup_ship_script.py tests/test_node_backup_role.py tests/test_backup_repo_reinit.py tests/test_r2_backup_watcher_probe.py tests/test_r2_watcher_targets.py --no-cov -q` | **108 passed** in 8.76s |
| Full suite | `make test` | **INVALID as evidence — see the concurrency disclosure below**: `8 failed, 3028 passed, 16 skipped, 2 xfailed, 8 errors` at 380s, all 16 in the two BACKUP-058 test files, with `jinja2.exceptions.UndefinedError: 'node_backup_env' is undefined` at `node-backup-ship.sh.j2:82` — a *half-applied uncommitted edit made by another session while this run was in progress*, not the committed change |
| Lint | `make lint` | `All checks passed!`, `110 files already formatted` |
| Generator idempotence | `make sync-r2-watcher-targets` | `targets.txt unchanged` (committed file matches the SSOT) |
| Real restic output shape | `restic init` + `cat config --json` on **0.18.1** (host) and **0.19.1** (`restic/restic:0.19.1` image); piped through the template's and `probe.sh`'s `sed` | Both pretty-print the id on its own line; both `sed`s extract the correct 64-hex id. The tests' fake restic mirrors the real shape |
| Mutation: ship drops the replaced-repository comparison | revert-after run | 1 red (`test_a_replaced_repository_fails_before_writing_a_snapshot`) |
| Mutation: ship inits on *any* `snapshots` failure (the pre-fix behaviour) | revert-after run | 2 red (`test_a_transient_error_fails_without_init`, `test_init_is_gated_on_restic_exit_code_10_only`) |
| Mutation: probe accepts `-` as declared | revert-after run | 2 red (`…[repository id not declared]`) |
| Mutation: probe stops printing `repository_id` | revert-after run | 4 red |
| Archive pre-flight | `dotf spec archive --help` | third pre-flight **refuses** while `verification.md` "Promotion candidates" are unanswered (finding F2) |

Every mutation of mine was reverted with `git checkout --`.

### Concurrency disclosure (read this before acting on the evidence above)

**Another session was editing this worktree while this review ran.** At 02:16 MDT `git status` shows uncommitted changes to `node-backup-ship.sh.j2`, `backup.yml`, `probe.sh`, both BACKUP-058 test files and `verification.md` — i.e. in-flight work that addresses this review's F1 (the empty-marker fail-open: the template now reads "A marker that EXISTS says … whatever it holds"), F3 (`ENV={{ node_backup_env }}`, with `node_backup_env: "{{ deploy_env }}"` added to `backup.yml`) and F6 (the cross-reference comment between the two `sed`s).

Consequences, stated plainly:

1. **My `make test` result is not evidence about the committed change.** It failed on a transient state of that edit (`node_backup_env` referenced in the template before it was passed by `_render`), which is why all 16 failures are confined to the two files being edited. The focused 108-test run and `make lint` (both green) ran before that edit landed, against `4660c854`.
2. **This verdict describes the committed sha `4660c854` only** — the diff `49eac7f1...4660c854` that the launcher scoped. The uncommitted work is out of scope, and it will need its own fresh review once committed (contract-set files were not touched, so this review is not stale — it is simply about the earlier state).
3. **Warning for the other session, from this run's output:** at the state visible at 01:59 the rendered template referenced `node_backup_env` with no value supplied, and every BACKUP-058 render/execution test errored. The playbook now supplies it; `_render` now passes it (`tests/test_node_backup_role.py:93`); re-run `make test` on the committed tree before opening any PR from this worktree, because a partially-applied edit of this shape is invisible until a test renders the template.
4. My mutation runs used `git checkout --` on `node-backup-ship.sh.j2` and `probe.sh` at ~01:52, and a concurrent edit to those same files could have been reverted by it; if an edit was lost, that is the cause, not a flake.

### Spec and task alignment

- The two-layer design in `proposal.md` is what the diff implements: the node's marker gated on restic exit 10 (`node-backup-ship.sh.j2:96-160`), and the watcher's pinned id from `backup.r2.repository_ids` (`probe.sh:119-134`, `backup_destination.py:386-403`, `common.yaml:1962-1977`).
- AC1's measurement is recorded with the exact commands, exit codes and the four ids (`verification.md`), and the ids match `common.yaml`, `targets.txt` and each other — checked mechanically.
- AC2–AC4 map to named tests, all green: `test_first_ship_initialises_and_records_the_new_repository`, `test_an_existing_repository_is_adopted_without_init`, `test_a_recorded_repository_that_matches_ships_normally`, `test_a_transient_error_fails_without_init`, `test_a_repository_gone_after_prior_ships_fails_loudly_without_init`, `test_a_replaced_repository_fails_before_writing_a_snapshot`, `test_the_repository_is_recorded_once_a_snapshot_exists_even_if_retention_fails`, `test_no_temporary_marker_is_left_behind`, `test_init_is_gated_on_restic_exit_code_10_only`. The retention/marker-ordering and `mktemp` cases are exactly the two windows I would have attacked.
- AC5 maps to `test_each_breakage_fails_its_node_and_the_fleet[repository replaced|repository id not declared]` plus `test_the_probe_never_takes_a_lock` (the new `cat config` call carries `--no-lock --no-cache`), and the new field is additive on the node line while the rule reads the fleet line.
- AC6's prod assertions are recorded but cluster-bound; what is checkable here holds (ids consistent, generator idempotent, role writes no marker file).
- AC7 maps to `tests/test_backup_repo_reinit.py` (6 tests: marker path from the role's own defaults, no `ignore_unreachable`, `DEST` asserted against a declared map, one-host assert, read→journal→remove ordering, recipe refusals) plus the runbook section.
- Non-goals respected: no `restic check`/retention change, no Storage Box leg, no per-node credentials. The per-destination *shape* only.
- Proposal AC checkboxes for AC2–AC7 are still `[ ]` while `verification.md` maps evidence for each. **Deliberately not raised as a fix**: `proposal.md` is in the contract set, so ticking them now would stale this verdict; the evidence mapping in `verification.md` is the durable record.
- Note, not a finding against this diff: `platform.json`'s `source_commit` is a **blob** hash (`git cat-file -t 95731a45…` → `blob`), not a commit — pre-existing generator behaviour, surfaced only because the file was regenerated here.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | ship guard — fail-open state | A marker that **exists but is empty** is treated as "no marker", so `RECORDED=""` and a missing repository (exit 10) runs `init`: the deleted history comes back silently, which is the exact defect this spec exists to remove. The write is atomic (`mktemp`+`printf`+`mv`), so no committed path produces an empty marker; reachability is an operator `touch`, a restoring tool that truncates, or any external writer. Hardening: distinguish "file absent" from "file present, unreadable/empty" (`[ -e "$MARKER" ]`, refuse a blank id loud). | Reproduced this session with the real harness: rendered script + fake restic, marker zero-length, `snapshots` rc 10 → `verbs=['snapshots','init','cat','backup','forget']`, `rc=0`, marker rewritten to the new id; stderr shows no refusal | UNTESTED — no case covers "marker present but blank"; `test_first_ship_initialises_and_records_the_new_repository` covers only the *absent* marker | code + tests |
| Minor | REAL | archive bookkeeping | `verification.md`'s "Promotion candidates" lines are still the template's `<yes: path / no: reason>`, and "Test status" is unfilled; `tasks.md`'s Closing checklist is unticked. `dotf spec archive`'s **third pre-flight has no override flag** and refuses an unanswered line, so the archive cannot run today. Not a defect in the change, and the fix is outside the contract set, so it does not stale this verdict. | `dotf spec archive --help` (read this session); `verification.md` lines under "Promotion candidates" and "Test status"; `tasks.md` "Closing" | UNTESTED (mechanical gate, not a behaviour) | verification.md (+ tasks.md closing boxes are cosmetic) |
| Minor | REAL | operator message | `REINIT="make backup-repo-reinit NODE=… DEST=$DESTINATION ENV=<env>"` bakes the literal `<env>` into the refusal text (template line 82), so the printed command is not runnable as pasted. It fails loudly rather than wrongly: the target refuses `ENV=<env>` with its own message. | `node-backup-ship.sh.j2:82`; refusal pinned by `test_the_target_refuses_a_missing_node_all_nodes_a_missing_dest_and_a_non_fleet_env` | `test_a_repository_gone_after_prior_ships_fails_loudly_without_init` (asserts the message contains the override) | code (render `ENV=staging\|prod`, or state the env explicitly) |
| Minor | THEORETICAL | AC1 ↔ node path | Exit 10 was measured on the watcher's read path (read-only token, `--no-lock --no-cache`); the node ships with the write credential and takes locks. `verification.md` discloses this and argues restic reads `config` before any lock. Direction of error is safe: any other code takes the `*)` arm and fails without `init`, so the worst case is a new node that cannot initialise, not a silent re-init. | `verification.md` "What this does and does not prove for the node"; template `*)` arm | `test_a_transient_error_fails_without_init` (covers the non-10 path); the live new-node path is UNTESTED | verification.md (confirm at the next genuinely new node) |
| Minor | THEORETICAL | AC6 evidence | The four prod markers and the live four-node `healthy:1` run cannot be re-verified from the repo: they rest on the recorded run, not on a named re-runnable test. The control is fail-closed (a mismatch or `-` makes the node unhealthy), and the declared ids are internally consistent here. | `verification.md` AC6 tables; `common.yaml` ids = `targets.txt` ids = generator output | UNTESTED (cluster-bound) | verification.md |
| Minor | SPECULATIVE | maintainability | The id-extraction `sed` is duplicated in `probe.sh:122` and `node-backup-ship.sh.j2:130` with different fallbacks (unhealthy vs fatal exit). Each side has its own tests, but a future divergence in the shared "which field is the id" assumption would not necessarily be caught by the other side. | Both expressions read identically today (checked side by side) | probe: `test_each_breakage_fails_its_node_and_the_fleet`; ship: `test_a_replaced_repository_fails_before_writing_a_snapshot` | tests (a shared fixture) or code (a comment cross-referencing both) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every AC is met on the paths I could exercise; negative paths covered and mutation-proven; one fail-open state (empty marker) that no committed code produces. |
| Verification       | B | Named tests per criterion, two mutation tables, and reproducible focused commands; the full-suite line and the promotion lines are unfilled, and AC6 is cluster-bound. |
| Scope              | A | Diff matches the proposal's two layers plus the tasks' named deliverables (lesson, CLAUDE.md line, runbook, Makefile target); no creep beyond the regenerated `platform.json`. |
| Reliability        | B | Fail-closed branch on every unexpected exit code, atomic marker write, marker written only after a snapshot exists, role re-run cannot touch it; the empty-marker and `<env>` soft spots keep it from A. |
| Maintainability    | B | Short functions, comments explain why, no dead code, behaviour pinned by executed tests; the duplicated id regex and the growing ship template are the drags. |
| Handoff-readiness  | B | Lesson-485, runbook section, CLAUDE.md gotcha and ADR rationale (`none`, with its reason) are in-diff; the archive gate still refuses because `verification.md`'s promotion/status/checklist fields are open. |

### Verdict

**PASS WITH GAPS** — no Blocker; the one Major is THEORETICAL (a fail-open state reproduced in the harness but not reachable from any committed code path), and the rest are Minor. Rubric has no C or D. Findings are tracked dispositions, not fixes owed before this verdict stands.

### Recommended next steps

Contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed** by this verdict — do not edit it, or this review goes stale. The items below live in `verification.md` / code / tests and can land freely:

1. **Fill `verification.md`'s "Promotion candidates" lines** (`no: …` for ADR and vault pattern; `yes: docs/lessons/storage-backup/lesson-485-…` for the lesson) and the "Test status" line — `dotf spec archive` refuses today without the first, with no override flag. Then archive.
2. **Disposition the Major in `verification.md`** as one of: applied, or ticketed with its root cause (the `[ -e ]` vs `-n "$RECORDED"` hardening and a named regression test for "marker present but blank"), or declined with a reason.
3. Optional, same round if cheap: render `ENV=staging|prod` instead of the literal `<env>`; add a cross-reference comment between the two id-extraction `sed`s.
4. At the next genuinely new node, record the node-side exit-10 observation (or its absence) against AC1's residual.
