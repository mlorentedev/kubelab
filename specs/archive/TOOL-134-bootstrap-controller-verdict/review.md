---
spec: "TOOL-134-bootstrap-controller-verdict"
verdict: "PASS"
reviewed_sha: "ffa73d39b1f02bc81d74c87bcbf8354d6abda35e"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-11"
---

## Adversarial review

**Scope**: TOOL-134-bootstrap-controller-verdict
**Sources**: `specs/TOOL-134-bootstrap-controller-verdict/{proposal,tasks,verification}.md`, `git diff 528277716723dd0b8379f5dc7095b01a746e64a3...HEAD`

### Spec and task alignment
- **Proposal Acceptance Criteria**: All 5 acceptance criteria defined in `proposal.md` (AC1: install path reaches hand-off and exits 0; AC2: failed prerequisite blocks hand-off and unresolved count is accurate; AC3: `--check` models passworded sudo without attempting install; AC4: no path blocks on password prompt and `as_root` never invokes sudo without `-n`; AC5: `apt-get update` runs without `-qq`) are implemented in `scripts/bootstrap-controller.sh` and backed by explicit tests in `tests/test_bootstrap_controller_script.py`.
- **Task Tracking Alignment**: In `specs/TOOL-134-bootstrap-controller-verdict/tasks.md`, all 25 checkboxes remain unchecked (`- [ ]`) despite the implementation having landed across commits `d7295c12` (#3310) and `ffa73d39` (#3314). While the contract digests match and `dotf spec digest` normalisation explicitly ignores checkbox ticks, the unticked state is tracked below as a minor spec-hygiene finding.
- **Verification Matrix Alignment**: `features.json` contains all 5 acceptance features (f1–f5) mapped to targeted pytest commands with captured execution evidence.
- **Documentation & Promotion**: Lesson 738 (`docs/lessons/toolkit-tooling/lesson-738-a-diagnostic-that-counts-as-a-failure-blocks-the-machine-it-serves.md`) is recorded, indexed in `docs/lessons/toolkit-tooling/_index.md`, and validated by `tests/test_check_lessons.py`. The runbook `docs/runbooks/ansible-controller.md` was updated with the new behavior and verified by `tests/test_runbook_targets_exist.py`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec-hygiene | All checkboxes in `tasks.md` remain unticked (`- [ ]`) despite implementation and test coverage being fully in place. | `specs/TOOL-134-bootstrap-controller-verdict/tasks.md` lines 20–75 | N/A (spec artifact) | spec (`tasks.md`) |
| Minor | THEORETICAL | diagnostic-clarity | In `--check` mode, if GNU make is installed but Poetry is absent, line 260 runs `poetry run toolkit version`, which fails with command not found and reports `[FAIL] the project venv is not installed` instead of noting that Poetry is missing. | `scripts/bootstrap-controller.sh` lines 258–263 only gate on `! have_gnu_make`. | UNTESTED | code (`scripts/bootstrap-controller.sh`) |
| Minor | THEORETICAL | test-isolation | `tests/test_bootstrap_controller_script.py::_run` creates a temporary directory via `tempfile.mkdtemp` when `path_prefix` is set, leaving unmanaged directories in OS temp. | `tests/test_bootstrap_controller_script.py` line 117 | UNTESTED | tests (`tests/test_bootstrap_controller_script.py`) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All 5 criteria met and verified; negative paths (failed sudo -n, missing root, failed apt, missing curl) handled. |
| Verification       | A | Reproducible tests for all ACs; mutation testing confirmed red-green sensitivity on both static and dynamic guards. |
| Scope              | A | Focus strictly maintained on controller bootstrap control flow, privilege probing, diagnostic clarity, and testing. |
| Reliability        | A | Non-blocking execution guaranteed via `sudo -n`; `set -euo pipefail` preserved; cached privilege probe avoids multiple sudo prompts. |
| Maintainability    | A | High cohesion with modular helper functions (`can_root`, `require_root`, `as_root`), CC ≤ 5 per function, clear in-code rationale. |
| Handoff-readiness  | B | Lesson 738 registered and runbooks updated, but `tasks.md` checkboxes were left unticked. |

### Verdict
PASS

### Recommended next steps
- **Archive Advisability**: Archiving this spec via `dotf spec archive TOOL-134-bootstrap-controller-verdict` is **advisable**. Contract digests match `review-request.json`, promotion candidates in `verification.md` are answered with valid file paths/reasons, and no `[AGENT-DRAFT]` tags exist.
- **Contract set rule**: Because the verdict is PASS, the contract set (`proposal.md`, `tasks.md`, `features.json`) is closed; do not edit `tasks.md` now, as changing contract files outside of a re-review would invalidate review staleness checks.
- **Follow-up tracking**: The minor diagnostic clarity improvement for `--check` when make is present but Poetry is absent can be tracked as a low-priority polish item in the bitácora backlog.
