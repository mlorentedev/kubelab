---
id: lesson-712-xdist-loadgroup-ignores-every-group-on-pytest-9-2
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pytest, xdist, testing]
---

# With pytest 9.2, `--dist loadgroup` ignores every `xdist_group` marker and says nothing

**Context**: #3078 parallelised `make test` with `pytest-xdist`. The plan was `--dist loadgroup`, plus `@pytest.mark.xdist_group` on the tests that share state.

**Problem**: `tests/test_every_generator_renders.py` was marked and still spread over four workers. A minimal file outside the repository did the same: eight tests in one group landed two per worker. pytest-xdist 3.8.0 marks a group by rewriting `item._nodeid`. pytest 9.2 keeps the node id in `item._id`, so the rewrite is lost and `loadgroup` schedules exactly like `load`. The marker is registered, the flag is accepted, the run is green, and nothing is grouped (pytest-dev/pytest-xdist#1407; the fix is merged upstream but unreleased as of 2026-11-04). A guard that only read the Makefile for `--dist loadgroup` passed throughout.

**Solution**: `make test` runs `--dist loadfile`. Each file goes to one worker in collection order, so a module-scoped fixture sees the same sequence a serial run gives it. `tests/test_pytest_parallel_config.py` now runs the recipe's own `--dist` value against a probe file in a nested pytest. It asserts that one worker ran every case, in order. Against `loadgroup` it fails and prints the split.

**Rule**: Test a scheduling or isolation option by running it and observing where the work went. Reading the configuration only proves the flag is spelled right, and an option that degrades silently stays green that way. When a dependency bump changes private attributes (`_nodeid` → `_id`), a plugin can keep running without doing its job.

**Tags**: `#pytest` `#xdist` `#issue-3078`
