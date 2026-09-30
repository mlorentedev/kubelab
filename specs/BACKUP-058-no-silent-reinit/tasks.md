---
tags: [spec, tasks]
created: "2026-09-29"
---

# Tasks - BACKUP-058-no-silent-reinit

> TDD order. One task = one focused commit. `[P]` = no dependency on an unchecked task; `[AC<n>]` = serves that acceptance criterion in `proposal.md`.
>
> **Two PRs, split by layer** (operator, 2026-09-29): PR1 is the node side, PR2 the watcher side. The measurement (task 1) lands with PR1. Neither PR carries a closing keyword for #1921. Both say `Refs #1921`, and only the archive PR closes it (lesson-483).
>
> Single-file test runs use `poetry run pytest <file> --no-cov -q` (what `make test` runs, narrowed). `make test` runs before each push.

## Setup

- [x] Worktree `~/Projects/kubelab-backup-058-wt`, branch `fix/backup-058-no-silent-reinit` from `origin/master` (`acad52e5`), `make worktree-init` done
- [x] `proposal.md` complete; names, key and PR split approved by the operator (2026-09-29)
- [x] R1 and R2 resolved by task 1 (2026-09-30, `verification.md`)

## Implementation

### Measurement (blocks both PRs)

- [x] [AC1] **Measure restic 0.19.1 exit codes on R2 with the read-only credential.** Follow the throwaway-Job procedure in `specs/archive/BACKUP-055-r2-watcher-probe/verification.md` (AC3): `kubectl create job --from=cronjob/r2-backup-watcher` in staging, with the command patched per run. Never edit the shared Secret or the bucket. Runs:
  1. `restic -r <prefix>/backup-058-does-not-exist --no-lock --no-cache snapshots -q`. Expected: `rc=10`.
  2. The same against a real repository with `RESTIC_PASSWORD` overridden to a wrong value. Expected: `rc=12`.
  3. The same with `AWS_ACCESS_KEY_ID` overridden to an invalid one. Expected: `rc=1` (any code other than 10 is acceptable; record it).
  4. `restic -r <prefix>/<repo> --no-lock --no-cache cat config --json` for each of the four repositories. Expected: `rc=0` and an `id` each. These four IDs are PR2's declarations.

  Record the table (command, rc, first stderr line) and the four IDs in `verification.md`. **If run 1 does not return 10, stop and re-plan with the operator.** Delete the Jobs afterwards.

### PR1: the node refuses to re-initialise

- [x] [AC4] Create `tests/test_node_backup_ship_script.py` (execution tests; `test_node_backup_role.py` stays render-only as its docstring promises). Harness:
  - Render `node-backup-ship.sh.j2` with every path under `tmp_path`: `node_backup_restic_install_path` pointing at a fake restic, the three credential files as dummy files, the staging dir and sentinel present, the heartbeat token file absent (which skips that block), and `node_backup_repository_id_dir` set to `tmp_path/state`.
  - Run the rendered script with `bash`.
  - The fake restic skips `--repo X --stuck-request-timeout Y` and appends each subcommand to a call log. It returns the `snapshots` exit code from a fixture file, answers `cat config --json` with `{"id":"<fixture id>"}`, and exits 0 for `init`, `backup` and `forget`.
- [x] [AC4] Write the five failing cases. Each asserts on the call log (whether `init` appears) and on the marker file:
  - first run (rc 10, no marker): `init` once, script exit 0, marker holds the new ID;
  - adoption (rc 0, no marker): no `init`, exit 0, marker holds the existing ID;
  - transient error (rc 1): no `init`, non-zero exit;
  - repository gone after prior runs (rc 10, marker present): no `init`, non-zero exit, stderr names `r2`, the expected ID and `make backup-repo-reinit`;
  - replaced repository (rc 0, marker ID differs from `cat config`): no `init`, no `backup`, non-zero exit.

  Run `poetry run pytest tests/test_node_backup_ship_script.py --no-cov -q`. Expected: FAIL (the current script calls `init` on rc 1 and writes no marker).
- [x] [AC2] [AC3] Add the role defaults `node_backup_repository_id_dir: /var/lib/node-backup` and `node_backup_r2_repository_id_file: "{{ node_backup_repository_id_dir }}/r2.repository-id"` to `infra/ansible/roles/node_backup/defaults/main.yml`, and a `state: directory` task (root, `0700`) to `tasks/main.yml`. The role creates the directory and never the file.
- [x] [AC2] [AC3] Rewrite `node-backup-ship.sh.j2:69-81`:
  - capture the `snapshots` rc inside the `if`'s `else`, not after it, because of `set -e`;
  - branch on 10, with the measured date in the comment;
  - compare `cat config` against the marker on every run;
  - write the marker only after `backup` and `forget` succeed.

  Re-run the new test file. Expected: 5 passed.
- [x] [AC2] Add a render assertion to `tests/test_node_backup_role.py`: the template branches on the literal exit code `10` and never runs `init` outside that branch. This is `features.json` f1's verification.
- [x] [AC7] Write a failing static test, `tests/test_backup_repo_reinit.py`. The playbook `infra/ansible/playbooks/backup-repo-reinit.yml` must:
  - use the same `node_backup_repository_id_dir` variable as the template (the `test_credential_file_paths_are_the_same_variable_on_both_sides` pattern);
  - have no `ignore_unreachable`;
  - `assert` that `dest` is in a declared list (`[r2]`);
  - read and `debug`-log the marker before `file: state=absent`.

  The Makefile target must refuse an empty `NODE`, `NODE=all` and an empty `DEST`. Expected: FAIL (the files do not exist).
- [x] [AC7] Write `infra/ansible/playbooks/backup-repo-reinit.yml` and the `backup-repo-reinit` Makefile target, which generates the inventory and then calls `$(TOOLKIT) infra ansible run -p backup-repo-reinit -e $(ENV) -l $(NODE) --extra-vars dest=$(DEST)` next to `backup-node`. Re-run. Expected: PASS. Dry-run verified 2026-09-30 against rpi3 (rc 0), and refused for `DEST=bogus`, `NODE=vps,rpi3`, `NODE=all`, a missing `DEST` and `ENV=dev`. The seven other targets that run a playbook without generating the inventory are #1941 (TOOL-090).
- [x] [AC7] Runbook: add a section "Repository missing or replaced" to `docs/runbooks/offsite-backup-restore.md`. It covers the node's message, the override `make backup-repo-reinit`, then the PR that updates `backup.r2.repository_ids`. The watcher's reason strings (`repository id changed`, `repository id not declared`) join the alert table in PR2, with the code that emits them.
- [x] Knowledge:
  - Lesson: `docs/lessons/storage-backup/lesson-485-init-if-it-does-not-open-turns-a-deleted-backup-into-a-healthy-empty-one.md`, the measured codes the design rests on, registered in `_index.md`.
  - CLAUDE.md: one sentence in the PVC-backup gotcha naming the marker and `backup-repo-reinit`.
  - ADR: `none`, because this is a control, not a placement decision. #471's ADR-049 amendment can cite it.
- [x] `make test` and `make lint` green. Open PR1 as a draft (`Refs #1921`, `## Knowledge` section), then mark it ready.

### PR2: the watcher pins each repository's identity

- [ ] [P] [AC5] Runbook: add the two watcher reasons to the alert table in `docs/runbooks/offsite-backup-restore.md`, linking "Repository missing or replaced".
- [ ] [P] [AC5] Extend `FAKE_RESTIC` in `tests/test_r2_backup_watcher_probe.py`: handle `cat config`, with the ID coming from a `<repo>.id` fixture. The targets fixtures gain the ID column. Add two parametrized breakages: an ID mismatch (`reason: repository id changed`) and the `-` token (`reason: repository id not declared`). Both must produce node `healthy:0` and fleet `healthy:0`, and the node line must carry `repository_id`. Expected: FAIL.
- [ ] [AC5] Change `infra/k8s/base/services/r2-backup-watcher/probe.sh`: read the third column, call `restic_read cat config --json`, compare, and print `repository_id`. Re-run. Expected: PASS, and the existing cases still pass.
- [ ] [AC5] Write a failing test in `tests/test_r2_watcher_targets.py`: `render_watcher_targets` emits `<node> <url> <id|-> <sources>...` from `backup.r2.repository_ids`. Then change `toolkit/features/backup_destination.py` (the generator and `_WATCHER_TARGETS_HEADER`). Expected: PASS.
- [ ] [AC6] Declare the four IDs from task 1 in `common.yaml` under `backup.r2.repository_ids`, with a comment on what the IDs are and how they change (`backup-repo-reinit` + PR). Run `make sync-r2-watcher-targets` and commit the regenerated `targets.txt`. `tests/test_r2_watcher_targets.py` must be green against the committed file.
- [ ] `make test` and `make lint` green. Open PR2 as a draft (`Refs #1921`), then mark it ready.

### Deploy and verify (after both merge)

- [ ] [AC6] Deploy the role: `make backup ENV=prod`. Re-run it: `changed=0`.
- [ ] [AC6] `make backup-node NODE=vps ENV=prod` and `NODE=rpi3`. Then read each marker through a toolkit/Ansible path and check it equals the declared ID.
- [ ] [AC6] After the next watcher run, `toolkit obs logs` shows four `r2_backup_node` lines with `healthy:1` and a `repository_id` matching each declaration, and `obs015-r2-backup-health` is Normal.
- [ ] [AC6] `beelink` and `rpi4`: record their markers in `verification.md` at their next power-on.

## Closing

- [ ] Every acceptance criterion is covered by at least one test or recorded measurement
- [ ] Every acceptance criterion has a `features.json` entry with a non-vacuous verification command
- [ ] `make lint` and `make test` pass
- [ ] No unrelated changes in either diff
- [ ] `verification.md` filled in
- [ ] Independent `dotf spec review` (different model from the implementer), then the archive PR with `Closes #1921`
