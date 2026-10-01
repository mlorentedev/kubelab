---
spec: "BACKUP-071-ace2-drills"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "ef241218fd16a184e3608133a8c88e053584163e"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: BACKUP-071-ace2-drills — the whole change, `git diff ed7476eb1f5473a0da30bc42b552f591b2babc03...HEAD` (round 1 fixes included, not re-reviewed as a delta).
**Sources**: `specs/BACKUP-071-ace2-drills/{proposal,tasks,verification,features.json}`; `toolkit/features/drill_remote.py`, `toolkit/features/{gitea,headscale}_drill.py`, `toolkit/cli/backup.py`, `toolkit/main.py`, `Makefile`, `infra/ansible/roles/{dev_node,node_backup}`, `docs/runbooks/offsite-backup-restore.md`, `tests/test_{drill_remote,headscale_drill,gitea_drill,restic_install_shared,node_backup_role}.py`.

### Spec and task alignment

- Every implementation box in `tasks.md` is `[x]`; the single open box is the review itself. AC1–AC5 each map to a diff artifact and a `features.json` entry.
- The round-1 FAIL (a) was absorbed honestly, not papered over: `proposal.md` §2 and AC3 now claim only what the test proves ("the remote entrypoint's drill path never builds a `ConfigurationManager`"), and the process-wide "ace2 decrypts nothing" claim was moved onto the AC1 gate (`! command -v sops`). Lesson-502 records why the original test could not have caught the import-time construction (#2021).
- Independently verified in this session:
  - `pytest tests/test_drill_remote.py tests/test_headscale_drill.py tests/test_gitea_drill.py tests/test_restic_install_shared.py tests/test_node_backup_role.py` → **140 passed, 0 failed** (fresh run at HEAD).
  - `ruff check` over every touched Python file → **All checks passed**.
  - Three mutations, each reverted with `git checkout HEAD --`: removing `</dev/null` from the `make worktree-init` step → `test_the_remote_script_keeps_stdin_for_the_drill` red; appending the payload to the ssh argv → both `test_no_injected_value_reaches_the_ssh_argv_and_the_payload_goes_on_stdin` params red; adding `apt: name=restic` to `drill_runtime.yml` → `test_no_other_task_file_downloads_restic` red. The gates round 1 added can fail.
  - `ansible-playbook --syntax-check infra/ansible/playbooks/provision-ace2.yml` passes, and fails with "the role '../roles/nonexistent_backup' was not found" when the `import_role: name: ../roles/node_backup` path is broken — so syntax-check really does resolve that relative role import (the task comment's claim holds).
  - The f5 gate command from `features.json`, run verbatim → rc=0.
  - `dev_node` is reached from `provision-ace2.yml` only (`- role: ../roles/dev_node`), so the new `dev_node_restic_version: ""` default cannot make another play fail its assert.
- **Not verified in this budget, marked UNVERIFIED rather than asserted:** the full `make test` at HEAD (started, still running at review time; the spec's `3435 passed` claim was made at `b2e3e44d`, two commits before the round-1 code fixes); the f1 gate (drives real provisioning on ace2) and the f2 gate (drives live drills). These are operational gates, not reproducible from a review sandbox; their evidence is recorded in `verification.md`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | verification / AC3 | AC3's "after a run, no file under the work directory contains an injected value" is exercised for the Headscale drill only. There is no Gitea counterpart, yet `verification.md` states the property without scoping it to Headscale. | `tests/test_drill_remote.py::test_a_real_restore_on_the_host_writes_no_injected_value_to_disk` wraps `headscale_drill.shutil.rmtree`; no sentinel-on-disk test exists in `tests/test_gitea_drill.py`. Mitigating read: `gitea_drill.py:295` passes `restic_env` only as `env=` to the restic subprocess and the token only into `GiteaClient`, so no plausible on-disk write was found — the risk is a coverage gap, not an observed leak. | UNTESTED (Gitea half); Headscale half named above | tests |
| Minor | REAL | CLI diagnosis | `preflight` prints `origin does not have <sha>; push it first` whenever no local `origin/*` ref contains HEAD — including when the commit *is* on the forge and only the local remote-tracking refs are stale. The runbook documents the workaround, but the operator is handed a wrong diagnosis. | `toolkit/features/drill_remote.py` (`preflight`); `docs/runbooks/offsite-backup-restore.md` §"Running a drill on ace2" itself says "if `origin/*` is stale, a pushed commit is refused too". | `test_a_tree_origin_cannot_reproduce_refuses_before_any_ssh[unpushed]` proves the refusal fires; no test asserts the message distinguishes staleness | code |
| Minor | THEORETICAL | error handling | The `except KeyError` in `drill_on_host` wraps both the config read (`get_plaintext_values()["networking"]`) and `ssh_target(...)`, so any `KeyError` raised while reading config is reported as `networking.nodes.<host> is not declared`. | `toolkit/features/drill_remote.py` (`drill_on_host`); `resolve_ssh_user` raises `KeyError` with its own message too. | `test_a_host_the_config_cannot_place_is_cannot_check` covers only the two intended cases; the misattribution path is UNTESTED | code |
| Minor | SPECULATIVE | reliability | Exit-code classes collide by value: ssh's own 255 and the script's 97 are also reachable as the remote drill's exit status, so a drill that exits with either is reported as "could not reach `<host>`" / "checkout could not be prepared". | `drill_remote.py` `SSH_FAILED`/`SETUP_FAILED` vs. `exec` making the drill's status the ssh status; no repro crafted. | UNTESTED | code |
| Minor | REAL | spec / evidence gate | `features.json` f4 (AC5) verifies the runbook with `grep -q 'HOST=ace2'` — a substring that survives deleting everything AC5 asks the section to explain (push first, what travels, what does not). This is the same class of under-tight gate that `#2017` fixed for f1 and f5. | The gate is a literal `grep -q 'HOST=ace2'`; the runbook's explanation can be removed with the command line intact and the gate still returns 0. | the gate itself, `features.json` f4 | spec artifact (`features.json` f4) — **disposition only**: the contract set is closed under this verdict; record accept-or-ticket in `verification.md` |
| Question / assumption | — | AC1 guarantee | The AC1 wording ("no `sops` on the non-interactive PATH") rests on the f1 gate at archive time; provisioning asserts only the age key's absence. A future role that installs `sops` on ace2 would leave the "ace2 decrypts nothing" guarantee resting on the key assert alone, with nothing failing at provision time. | `proposal.md` §2; `infra/ansible/roles/dev_node/tasks/drill_runtime.yml` asserts only `~/.config/sops/age/keys.txt`; f1 checks both. | `features.json` f1 (gate), not a unit test | surface only — confirm the residual risk is accepted |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | AC1–AC5 hold on the recorded runs and the negative paths (dirty tree, unpushed commit, malformed payload, secret-in-argv) are covered; the Gitea half of the AC3 disk property is untested. |
| Verification       | B | Reproducible gates with commands and recorded live output; f4 is a substring gate and the `make test` figure predates the round-1 code fixes. |
| Scope              | B | Diff matches the proposal (IaC, remote runner, CLI/Make, runbook, lesson, drill split); a `yamllint disable-line` and formatter-only lines in `dev_node/tasks/main.yml` are side-changes, already dispositioned in round 1. |
| Reliability        | B | Refuses a dirty/unpushed tree before any ssh, every remote failure is CANNOT CHECK, provisioning idempotent live (`changed=0`); exit-code conflation is a minor unhandled case. |
| Maintainability    | B | Small functions, no dead code, ruff clean, WHY-comments; `_git` carries an unused `env` parameter. |
| Handoff-readiness  | A | Lesson-502 captured in-session, runbook section added, BACKUP-040/067 verification updated, archive checklist present. |

### Verdict

PASS WITH GAPS

Rubric has no C and no D (all B or above → PASS); one open Major is THEORETICAL, not REAL (→ PASS WITH GAPS is the more severe of the two paths). No Blocker found. `dotf spec archive` is **advisable** in the current state, provided the four non-contract items below are dispositioned in `verification.md` or carried into a follow-up ticket.

### Recommended next steps

All of these land **outside the contract set**, so none of them invalidates this review:

- **tests** — add the Gitea counterpart of `test_a_real_restore_on_the_host_writes_no_injected_value_to_disk` (sentinel secrets, teardown inspected before removal), or record in `verification.md` that the property is proved for Headscale and argued by construction for Gitea. Finding 1.
- **code** — make `preflight`'s unpushed refusal name staleness as a possible cause (e.g. "or `origin/*` is stale — `git fetch origin`"), and narrow the `except KeyError` in `drill_on_host` to the `networking` read. Findings 2 and 3.
- **spec** — leave `features.json` f4 as it is (the contract set is closed); write the disposition of its weak gate into `verification.md`, or open a follow-up ticket to tighten it the way f1/f5 were tightened. Finding 5.
- **Question** — confirm and record that the `sops`-absence half of the AC1 guarantee is intentionally gate-only, not provision-enforced.
- **Evidence** — re-run the full `make test` at `ef241218` and record the summary line in `verification.md`; the figure there is from `b2e3e44d`, before the round-1 code fixes.

### Post-review state (added after the verdict was written)

While this review ran, a parallel session committed `1cb1538d` ("the gitea drill on a host writes no injected value to disk either") on top of the reviewed commit. It touches `tests/test_drill_remote.py`, `toolkit/features/drill_remote.py` and `toolkit/features/gitea_drill.py`, and appears to apply findings 1–3 above (a Gitea sentinel-on-disk test, the `preflight` refusal naming stale `origin/*` refs, and the narrowed `except KeyError`).

- This verdict is for `ef241218`, the commit examined; `1cb1538d` is **not re-verified** here, and findings 1–3 should be re-judged against it (UNVERIFIED).
- The **contract set is untouched** by `1cb1538d` (`proposal.md`, `tasks.md`, `features.json` unchanged), so the `review-request.json` contract digests still match and `dotf spec archive`'s staleness check is satisfied.
- The changes in `1cb1538d` are implementation/tests only; the remaining findings (4, 5, and the AC1 question) are unaffected.
