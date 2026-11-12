---
tags: [spec, verification, templates]
created: "2026-11-08"
id: "TOOL-134-bootstrap-controller-verdict"
type: spec-verification
status: active
owner: manu
---

# Verification - TOOL-134-bootstrap-controller-verdict

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 (install path reaches the hand-off and exits 0) -> `test_install_path_hands_off_after_installing` passes; `test_install_path_still_refuses_when_an_install_fails` keeps the refusal honest when an install genuinely fails
- [x] AC2 (`--check` reports a passworded sudo and exits 1) -> `test_check_mode_reports_a_passworded_sudo` passes; `test_check_mode_counts_one_missing_prerequisite_as_one_failure` pins the count to the one thing actually wrong
- [x] AC3 (no path blocks on a prompt) -> `test_as_root_never_invokes_sudo_without_dash_n` and `test_install_mode_does_not_attempt_apt_without_root` pass
- [x] AC4 (`apt-get update` failure is legible) -> `test_apt_update_is_not_quiet_quiet` passes

## Test status

- Test suite: `python -m pytest tests/test_bootstrap_controller_script.py tests/test_runbook_targets_exist.py -q -o addopts=""` -> **115 passed in 5.61s** (18 bootstrap tests: 6 new for the verdict, 1 new for the count, 11 pre-existing). Executed inside WSL (Ubuntu 24.04, ext4) because the `@_posix` tests skip on Windows; the file's contract is POSIX shell semantics, so native Windows is not a valid environment for it.
- Red before green: `test_check_mode_counts_one_missing_prerequisite_as_one_failure` was run against the pre-fix block and failed on `assert '[ERROR] 1 check(s) failed' in ...` (`[ERROR] 2 check(s) failed` was emitted). The fixture needed a stub `poetry` too — without one the host has two genuine misses and `1` would have been the wrong assertion for the wrong reason.
- Lint: `ruff check tests/test_bootstrap_controller_script.py` -> `All checks passed!`; `ruff format --check` -> `1 file already formatted`. The script itself is shell, so `ruff` does not apply and `shellcheck` is not installed here (it is not in `.pre-commit-config.yaml` either); `bash -n scripts/bootstrap-controller.sh` -> syntax ok.
- Manual smoke test: `--check` was run against a copy of the tree with no `.venv`. It reports `[ok]` for python3, make and poetry, then `[FAIL] the project venv is not installed, so ansible-core cannot be verified` and exits 1 — the correct verdict for that copy, and proof that the check no longer reports success on a machine that cannot run Ansible.
- Observed on the affected host (the report that opened the issue, WSL 2026-11-08): make and Poetry installed successfully and the script still ended `[ERROR] 2 prerequisite(s) above are unresolved; not handing off to make`. That exit is now unreachable on that path.
- Observed on the seat's WSL 2026-11-09, healthy host, script in place: `RC=0`, `[SUCCESS] All 4 checks passed — this machine can run Ansible`. Same script with `make` removed from `PATH` and `sudo -n true` failing: `RC=1`, `[ERROR] 1 check(s) failed` on stderr, `[FAIL] GNU make is missing` as the only verdict, root reported as two notes.
- No regressions in existing test suite: yes — the 11 pre-existing tests in the same file are unchanged and green; `grep` confirms no other test reads `scripts/bootstrap-controller.sh`. `tests/test_runbook_targets_exist.py` covers the runbook edits (114 passed on its own).

## Decisions made during implementation

- The verdict moved; the counter did not learn arithmetic. `bad()` now fires only at a point of no return (`--check`, or a failed install) and the recoverable pre-install state is reported by a new `note()`. The rejected alternative was decrementing `FAILED` inside `ok()`: it makes correctness depend on `bad`/`ok` being paired at every call site, which is exactly the invariant that was violated.
- Privilege is probed once (`can_root()` -> `ROOT_OK`) rather than per call site, so a passworded `sudo` costs one non-interactive failure instead of a hang on each of the three root operations.
- The `--check` mode delegates the Ansible verdict to `make check-ansible` instead of re-deriving it, so the doctor has one definition. It only pre-empts that with its own `bad` when there is no project venv, because `poetry run toolkit` cannot exist without one and the failure would otherwise read as an Ansible problem.
- Poetry's install path is deliberately **not** gated on root: the official installer writes to `~/.local/bin`, so demanding root there would refuse an install that does not need it.
- In `--check`, root is a **note**, not a verdict. Nothing gets installed, so root gates an attempt that will not happen; counting it answered `2 check(s) failed` to a host with one problem, and the count is what the operator triages against. `require_root()` keeps its `bad` for the install path, where root really is a point of no return.
- The tests had to isolate `HOME`, not just `PATH`. The script prepends `$HOME/.local/bin` when a `poetry` exists there, so on a seat where the operator had just installed Poetry that way, the real binary shadowed the stub and the test stopped testing what it claimed. Same class of leak for `true` in the stubbed `sudo`.
- A `--check` run of a **copy** of the script reports a missing project venv and exits 1 while `poetry run toolkit version` succeeds by hand. Not a defect: the script anchors itself (`ROOT="$(cd "$(dirname "$0")/.." && pwd)"`), so a copy in `/tmp` resolves `ROOT=/`. Probing it against a real environment means placing it under `<repo>/scripts/` — a measurement artifact worth recording because the message it produced accused the environment.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/toolkit-tooling/lesson-738-a-diagnostic-that-counts-as-a-failure-blocks-the-machine-it-serves.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a defect in one bootstrap script's control flow, and the pattern it produced is captured as a lesson rather than as an architectural choice
- [x] New pattern candidate for `00_meta/patterns/`? no: the rule ("emit the verdict at a point of no return, never count diagnostics") is stated in the lesson and does not yet recur across projects


## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [x] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
