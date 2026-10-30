---
id: lesson-668-a-subprocess-check-in-a-fixture-hides-the-stderr-that-names-the-cause
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pytest, docker]
---

# A `check=True` subprocess in a fixture hides the stderr that names the failure

**Context**: `tests/loki_harness.py` starts the pinned Loki with `docker run`, called with `capture_output=True, check=True`. CI run 40854256126 ended with 15 errors in `tests/test_r2_backup_freshness_rule.py`, all `CalledProcessError: ... returned non-zero exit status 125` (#2792).

**Problem**: Exit 125 is Docker's own failure, before any container exists: a pull refused or rate-limited, or a daemon error. The `CalledProcessError` held Docker's stderr, but its message is only the command and the exit status, and pytest's report prints the message. The one line that said which failure it was appeared nowhere in the log. The harness already failed with the container's logs when Loki never became ready. The step before it had no such handling.

**Solution**: `run_loki()` reads `returncode` itself and calls `pytest.fail` with Docker's stderr. `tests/test_loki_harness.py` puts a fake `docker` on `PATH` that writes a rate-limit message and exits 125, and asserts the message reaches the failure.

**Rule**: In a fixture or harness, never let `check=True` raise from a command whose stderr explains the failure. Check the return code and fail with stderr in the message.

**Tags**: `#pytest` `#docker` `#issue-2792`
