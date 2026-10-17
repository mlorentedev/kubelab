---
id: lesson-570-pytest-says-whether-a-selector-matched-in-its-exit-code-not-in-its-collect-output
type: lesson
status: active
created: "2026-10-14"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, pytest, specs, guards]
---

# pytest says whether a selector matched in its exit code, not in its collect output

**Context**: Sweeping every active spec's `features.json` for verification commands that select no test (#2180), by running each with `pytest --collect-only` and counting the node ids it printed.

**Problem**: The first sweep reported zero tests for every command, including ones that select dozens. `-q` on top of this repo's `addopts` leaves `--collect-only` printing only the summary line, so there were no node ids to count. A count parsed from output depends on verbosity flags the parser does not own, and it answered wrong in the direction that looks like a finding.

**Solution**: Judge by the exit code, which no flag changes. 0 is something collected, 5 is nothing collected (a selector that matches no test in files that exist), 4 is a usage error (a named file or node id that does not exist). The two failure classes come apart for free: 5 is always a defect; 4 with pytest's `not found:` is the expected state of a pending feature whose tests are not written yet, and any other 4 is a malformed command. Neither the code nor the message tells an unwritten test from a renamed or deleted one, so the guard exempts only the pending features declared in its `UNWRITTEN` set, and an entry whose tests now collect fails until it leaves the set. `tests/test_spec_verifications_select_tests.py` does this for 39 distinct commands in about ten seconds.

**Rule**: When a tool reports an outcome in its exit code, read the exit code. Parse output only for what the code cannot say, and never for a count whose formatting other flags control.

**Tags**: `#pytest` `#specs` `#issue-2180`
