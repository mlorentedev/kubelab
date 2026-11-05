---
id: lesson-710-a-parallel-test-run-finds-shared-state-a-serial-run-hides
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pytest, xdist, testing]
---

# A parallel test run finds shared state that a serial run hides, and grouping is not always the fix

**Context**: `make test` moved from one pytest process to `pytest-xdist` (`-n auto --dist loadgroup`, #3078). The serial suite passed, and a first parallel run with `--dist loadfile` passed too.

**Problem**: Three kinds of shared state showed up only once tests ran side by side, or only by comparing coverage:

- `tests/test_every_generator_renders.py` built each generator, then set `project_root` to a copy of the repo. `WikiGenerator` had already derived its output directory from the real root in `__init__`, so every run wrote `apps/wiki/generated_docs` into the checkout. The path is gitignored, so `git status` stayed clean. The only sign was a one-branch coverage difference between two runs, because `apps/` had grown a directory between them.
- `tests/test_host_client_barrier.py` wrote its probe file into `tests/` under a name built from `tmp_path.name`. Each xdist worker has its own basetemp, so two workers hand out the same name for the same test, and one deleted the other's file (`FileNotFoundError`, one run in two).
- Two tests bound a port with `bind(0)`, closed the socket, and then relied on it: one handed it to `docker run -p`, one counted on nothing listening there. Once the socket is closed, any other worker can take that port.

**Solution**: Each one was fixed where the problem was. No test was deselected or grouped:

- `WikiGenerator.wiki_docs_path` is now a property, so it follows `project_root` (`tests/test_wiki_generator_follows_project_root.py`).
- The probe file is named with `uuid4`.
- Docker picks the host port (`-p 127.0.0.1::1053/udp`, then `docker port`), and the refused-port test keeps its socket bound and not listening for the whole test.

**Rule**: Compare a parallel run to a serial run on three things: the failure set, `lines-covered`/`branches-covered` in `coverage.xml` (not the rounded total), and the ignored files in the checkout (`git status --ignored`). A difference in any of them is shared state until proven otherwise. An `xdist_group` marker only keeps tests in the same group off each other. It does nothing about every other worker, so a host port or a path outside `tmp_path` needs a fix in the test, not a marker.

**Tags**: `#pytest` `#xdist` `#issue-3078`
