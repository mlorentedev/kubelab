---
tags: [spec, tasks, templates]
created: "2026-11-08"
id: "TOOL-134-bootstrap-controller-verdict"
type: spec-tasks
status: active
owner: manu
---

# Tasks - TOOL-134-bootstrap-controller-verdict

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from main: `fix/bootstrap-controller-verdict`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

### AC1 — the verdict describes the state after the attempt

- [x] [AC1] Write failing test `test_install_path_hands_off_after_installing`: stub `PATH` with no
      `make` and no `poetry`, stub `apt-get` and `curl` so both installs appear to succeed,
      assert the script reaches the hand-off (`make setup-ansible` invoked) and exits 0
- [x] [AC1] Restructure the make block: `bad` fires only in `--check` or after a failed
      attempt; the pre-install state is `note`, not `bad`
- [x] [AC1] Restructure the poetry block the same way, keeping the `~/.local/bin` PATH export
- [x] [AC1] Verify the hand-off guard now counts only unresolved prerequisites; keep the
      existing `[ERROR] %d prerequisite(s) above are unresolved` wording

### AC2 — `--check` models privilege

- [x] [AC2] Write failing test `test_check_mode_reports_a_passworded_sudo`: stub `sudo` that
      fails for `-n` and succeeds otherwise, stub `make`/`poetry` absent, run `--check`,
      assert exit 1 and a message naming root/sudo
- [x] [AC2] Add `can_root()` (`id -u` = 0, else `sudo -n true 2>/dev/null`) and call it from
      the install branches and from `--check`
- [x] [AC2] In `--check`, report "root is not available without a password" and
      `note "run 'sudo -v' first, then re-run"`; in install mode, exit 1 before apt

### AC3 — nothing waits on a prompt

- [x] [AC3] Write failing test `test_as_root_never_invokes_sudo_without_dash_n`: assert the
      script text contains no bare `sudo "$@"` / `sudo ` invocation lacking `-n`
- [x] [AC3] Change `as_root` to `sudo -n "$@"`

### AC4 — apt failure is legible

- [x] [AC4] Write failing test `test_apt_update_is_not_quiet_quiet`: assert the make install
      path does not pass `-qq` to `apt-get update`
- [x] [AC4] Drop `-qq` from `as_root apt-get update`

### Closing work

- [x] Re-read the whole script end to end; the two install blocks must read the same way
- [x] Refactor for clarity (extract, rename, dedupe)
- [x] Confirm `--check` still installs nothing and still exits 1 for a genuinely broken machine

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [x] `poetry run pytest tests/test_bootstrap_controller_script.py -q` green
- [x] `poetry run pytest -q` green (no regressions)
- [x] `poetry run ruff check toolkit tests` and `poetry run mypy toolkit` clean
- [x] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [x] PR opened referencing this spec folder, body from `.github/pull_request_template.md`, `Closes #3234`

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.
