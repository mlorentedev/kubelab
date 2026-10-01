---
spec: "BACKUP-071-ace2-drills"
verdict: "FAIL"
reviewed_sha: "bd3bec168a3b8b3ee8ecd8b0ffd62483492c7b00"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: `BACKUP-071-ace2-drills` — the whole change, `git diff ed7476eb1f5473a0da30bc42b552f591b2babc03...bd3bec168a3b8b3ee8ecd8b0ffd62483492c7b00` (10 commits, 26 files, +1323/−126). The base is the commit the launcher resolved; `git merge-base --is-ancestor` confirms it is an ancestor of HEAD.
**Sources**: `specs/BACKUP-071-ace2-drills/{proposal,tasks,verification}.md`, `features.json`, `review-request.json` (contract digests); `toolkit/features/drill_remote.py`, `toolkit/features/{gitea,headscale}_drill.py`, `toolkit/cli/backup.py`, `toolkit/main.py`, `infra/ansible/roles/dev_node/tasks/drill_runtime.yml`, `infra/ansible/roles/node_backup/tasks/restic.yml`, `tests/test_drill_remote.py`, `tests/test_restic_install_shared.py`, `tests/test_node_backup_role.py`, `tests/test_headscale_drill.py`, `docs/runbooks/offsite-backup-restore.md`, `specs/BACKUP-040-gitea-restore-drill/verification.md`, `specs/BACKUP-067-headscale-restore-drill/verification.md`, `docs/lessons/toolkit-tooling/lesson-502-*.md`.

### Spec and task alignment

- Every implementation box in `tasks.md` is `[x]`; the only open box is the review itself. AC1–AC5 each have a diff artifact and a `features.json` entry, and no `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain (grep: 0 in all three spec files).
- **AC1** is delivered: `node_backup/tasks/main.yml` imports the new `restic.yml`, and `dev_node/tasks/drill_runtime.yml` pulls the same file through `import_role: name: ../roles/node_backup, tasks_from: restic`. I verified that resolution actually works (scratch role tree, `ansible-playbook`: shared task ran, `node_backup_restic_install_path` default loaded, `node_backup_restic_version` passed as 0.19.1), and `ansible-playbook --syntax-check` on `provision-ace2.yml` parses. `tests/test_restic_install_shared.py` (4) passes. The stated `changed=0` second provision and the `test ! -e ~/.config/sops/age/keys.txt` probe are ace2-only and **UNVERIFIED here** (host not reachable from this review).
- **AC2** is delivered in code: `--host`/`HOST=` route through `drill_on_host`, the live Headscale reads are split into `read_live`/`LiveState`, and the four exit classes are labelled (`255` ssh, `97` setup, otherwise the drill's own verdict). The two live ace2 runs are recorded in BACKUP-040/BACKUP-067 `verification.md`; I re-ran the f5 evidence gate over those files (rc=0) and over a decoy containing only a pending `HOST=ace2` mention (rc=1) — it is fail-closed. The runs themselves are **UNVERIFIED here**.
- **AC3** is delivered *only at the scope its own test can reach* — see Finding 1. `tests/test_drill_remote.py` (26) proves: no sentinel in ssh argv, payload on stdin, every setup step reads `/dev/null`, a malformed payload is named by exception class only, no sentinel in any file under the work tree before teardown (and the test asserts files were written, so it cannot pass vacuously).
- **AC4/AC5** are delivered and fail-closed (`grep -q 'HOST=ace2' docs/runbooks/offsite-backup-restore.md` passes; promotion candidates are all answered, which `dotf spec archive`'s third pre-flight requires).
- No test was deleted or weakened: `tests/test_node_backup_role.py` was re-pointed at `restic.yml` because the install moved, and the moved assertions are re-covered in `tests/test_restic_install_shared.py`.

I reproduced the four mutations the spec claims (verification.md "Test status"): a setup step reading stdin (1 failure), a malformed payload echoed (3), a dirty tree accepted (2), an ssh failure not classed (1). The tests are genuinely fail-closed for those paths.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | spec-vs-code, security claim | `proposal.md` §2 says "The remote process never constructs a `ConfigurationManager` and never touches SOPS", and AC3 says "the remote entrypoint never builds a `ConfigurationManager`". Both are false at process scope: importing `toolkit.cli.backup` builds one and calls into SOPS. | Spy on `ConfigurationManager.__init__`: `after importing toolkit.cli.backup: 1 [('dev', PosixPath(...))]`. Second probe: the import chain reaches `toolkit/features/configuration.py:81 subprocess.run(["which","sops"])` from `toolkit/config/settings.py:419 settings = get_settings()` via `get_env_vars()` → `get_merged_config()` → `_decrypt_sops()` — i.e. the import spawns the sops check (and, with sops present, `sops -d`). Mutation M6: a module-level `_CM("dev")` in `drill_remote.py` leaves all 26 tests green, because the guard patches `__init__` after collection. Mitigation that keeps this from being an exposure: on ace2 `sops` is absent and the age key is asserted absent by `drill_runtime.yml`, so nothing is decrypted — the recorded live runs print "SOPS is not installed" twice, and `lesson-502`/`#2021` document exactly this. The contract text and the guard nevertheless overstate what the code does. | `test_the_entrypoint_runs_the_drill_with_the_payload_and_reads_no_config` — named, but scoped below the claim (its own docstring: "covers the drill, not the process") → the process-level claim is **UNTESTED** | code (defer `settings = get_settings()`; TOOL-097/#2021) **or** spec (reword proposal §2 + AC3 to the tested claim) |
| Major | REAL | tests, gate coverage | AC1 says "A test fails if either role grows its own copy". The gate is narrower: it only inspects `get_url` tasks whose URL contains `restic_`, in `node_backup`/`dev_node` task files. Other acquisitions are invisible. | Mutation: appended `ansible.builtin.apt: name=restic` and an `ansible.builtin.unarchive` of a restic asset to `dev_node/tasks/drill_runtime.yml` → `tests/test_restic_install_shared.py tests/test_node_backup_role.py` = **53 passed**. | `test_no_other_task_file_downloads_restic` — named, does not cover these shapes → **UNTESTED** for them | tests |
| Minor | REAL | quality | The local path of `toolkit/cli/backup.py::_drill` calls the private `drill_remote._module`; a rename in `drill_remote` silently breaks the CLI with no test asserting the seam. | `git diff` of `toolkit/cli/backup.py`; no test imports or patches `_module` by name. | UNTESTED | code |
| Minor | THEORETICAL | resilience | `drill_on_host` indexes `ConfigurationManager(...).get_plaintext_values()["networking"]` before `ssh_target` guards the node; a config with no `networking` key is a raw `KeyError` traceback rather than CANNOT CHECK. | code read of `drill_remote.drill_on_host`; the happy path is covered (`test_a_clean_pushed_tree_sends_its_head` uses the real `common.yaml`), the empty-config path is not. | UNTESTED | code |
| Question | — | process | AC2's "a commit `origin` lacks" is decided from local remote-tracking refs (`git branch -r --contains`). With a stale `origin/*` the run refuses a commit that *is* pushed; the runbook says `git push` but never `git fetch`/`git remote update`. Conservative (refuses, never wrongly accepts), but the operator-facing failure mode is "CANNOT CHECK — origin does not have <sha>" on a pushed commit. | `drill_remote.preflight`; runbook "Running a drill on ace2". | `test_a_tree_origin_cannot_reproduce_refuses_before_any_ssh[unpushed]` covers the intended case only | spec (runbook) or code (fetch first) |
| Minor | SPECULATIVE | scope | Formatting-only edits unrelated to the spec: the GitHub apt-repo line rewrap, a removed blank line, and a `yamllint disable-line` in `dev_node/tasks/main.yml`. Harmless, undocumented, and not gating. | `git diff infra/ansible/roles/dev_node/tasks/main.yml`. | n/a | — |

Reality note on Finding 1: "REAL" here means the process behaviour is reproduced (import builds one; the chain reaches `_decrypt_sops`). The *harm* is bounded — no plaintext is decrypted on ace2 because both preconditions (`sops` binary, age key) are absent and the key is asserted absent by the same change. But the AC's claim has no covering test, and per the test-traceability gate an UNTESTED Major is not resolved by the implementer's disclosure in `verification.md` (which is outside the contract set and cannot make the claim true).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | Happy paths and negative paths are strong and the live runs are recorded, but AC3's process-level claim is false and AC1's gate is narrower than its stated contract. |
| Verification       | B | Reproducible commands, mutation battery (M1–M4 reproduced by me), and live transcripts; the one security claim that needs a subprocess test has none. |
| Scope              | B | Diff matches the proposal; only trivial formatting side-changes and no creep into out-of-scope drills. |
| Reliability        | B | Exit classes, `CANNOT CHECK` labels and unconditional teardown are sound; one unguarded `KeyError` path (Finding 4). |
| Maintainability    | B | Functions short, complexity low, names clear; one private-symbol reach from the CLI (Finding 3). |
| Handoff-readiness  | A | Runbook section, lesson-502, promoted lesson answered, BACKUP-040/067 evidence updated, feature gates made fail-closed. |

Rubric-only path would be PASS WITH GAPS (one C, no D). The severity × reality path is more severe: two REAL Majors, so the verdict is FAIL.

### Verdict
FAIL

### Recommended next steps

Contract-set edits are in play on a FAIL, and a re-review follows. Choose one of the two per finding:

1. **Finding 1 (AC3 / proposal §2).** Either make it true — remove the import-time construction (`toolkit/config/settings.py:419`, TOOL-097/#2021) so no `ConfigurationManager` is built and no sops check runs in the `--inputs-stdin` process, which is a small code fix and worth doing on its own — **or** reword proposal §2 and AC3 to the claim the test proves: "the drill's own code path builds no `ConfigurationManager` and reads no config; the process still builds one at import for `dev` (#2021)". Do not leave the current text with a test that cannot fail on it.
2. **Finding 2 (AC1 gate).** Widen `test_no_other_task_file_downloads_restic` to fail on any restic acquisition in either role's task files regardless of module (`apt`/`get_url`/`unarchive`/`shell`/`command`/`copy`), or reword the AC to the `get_url` scope it actually enforces.

Outside the contract set — carry these into `verification.md` as dispositions or a follow-up ticket, **not** into `proposal.md`/`tasks.md`/`features.json`:

3. Expose `module_for` (public) in `drill_remote` and stop calling `_module` from `cli/backup.py` (Finding 3).
4. Wrap the `get_plaintext_values()["networking"]` read so a missing key is CANNOT CHECK, not a `KeyError` traceback (Finding 4).
5. Add `git fetch` (or a note that the refusal is conservative) to the ace2 runbook section (Finding 5).

**Archive is NOT advisable in this state**: `dotf spec archive` refuses without a passing review, and this is FAIL. The minimum to flip it to PASS is items 1 and 2 plus a re-review; the untouched areas (payload-on-stdin, no-secret-in-argv, dirty/unpushed refusal, Headscale seam, idempotent provisioning, teardown) are sound and need no change.

### Evidence and coverage gaps in this review

- Ran fresh: `pytest tests/test_drill_remote.py tests/test_restic_install_shared.py tests/test_headscale_drill.py tests/test_gitea_drill.py tests/test_node_backup_role.py` → **138 passed**. `ansible-playbook --syntax-check provision-ace2.yml` → parses. `ansible-playbook` on a scratch role tree → shared-restic `import_role` resolves. The five mutation edits above were reverted; `git status` shows only `specs/BACKUP-071-ace2-drills/review-request.json` (launcher artifact) and this `review.md`.
- Full `make test` was still running when this was written; the touched-file suites are green. Treat the 3435-passed claim as the implementer's, not as mine.
- The two live ace2 drill runs, the `changed=0` provision, and the no-age-key probe on ace2 are **UNVERIFIED** by me (host unreachable from this review); I verified the *gates over the evidence* (f5) and the code that produces them.
