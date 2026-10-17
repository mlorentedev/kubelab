---
id: "lesson-562-a-same-length-mutation-outlives-its-restore-in-the-bytecode-cache"
type: lesson
status: active
title: "A same-length mutation outlives its restore in the bytecode cache"
created: "2026-10-13"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, mutation-testing, python, bytecode]
---

# A same-length mutation outlives its restore in the bytecode cache

**Context**: TF-007 PR 1a proved its guards with `make mutate`. One mutation
changed `0o600` to `0o644` in `toolkit/features/terraform_runner.py`, the test
went red, and the tool restored the file byte for byte. `git status` was clean.

**Problem**: The next `make test-fast` failed the same test on correct source:
`assert (True and 420 == 384)`, the mutant's mode. The child pytest had compiled
the mutant into the repository's `__pycache__`. Python accepts a `.pyc` whose
header matches the source's mtime, in whole seconds, and its size. A
same-length replacement, written and restored within one second, matches both,
so every later import ran the mutant. The header read `mtime 1791943113 size
13717` for both the `.pyc` and the restored source, and the code object held
`0o644`. It works the other way too: a cached original read during the mutant's
run hides the mutant, and the verdict is a false GREEN. `git status` cannot see
either, because `__pycache__` is ignored.

A second, smaller trap from the same session: `make mutate FROM='@$(_TF) dns
plan'` refuses with "matches 0 times", because make expands `$(_TF)` in a
command-line variable before the tool sees it. Write `$$(_TF)`. The refusal is
safe, but its message suggests that the text is absent from the file.

**Solution**: The child pytest runs with `PYTHONPYCACHEPREFIX` set to a
temporary directory that is removed after the run. It compiles from source and
leaves nothing in the repository. `tests/test_mutate.py::
test_the_mutant_never_reaches_the_repository_bytecode_cache` runs a real
same-length mutation and asserts that no `.pyc` lands in the repository. It
fails without the change. Clearing the poisoned cache once
(`find toolkit tests -name '*.pyc' -delete`) brought the suite back.

**Rule**: A tool that edits source and restores it must also isolate every cache
keyed on that source's metadata. A byte-identical restore does not undo a
derived artifact whose validity check is coarser than the edit. When a test
fails on code you just restored, check `__pycache__` before you check the code.

**Tags**: `#mutation-testing` `#python` `#bytecode` `#tool-100`
