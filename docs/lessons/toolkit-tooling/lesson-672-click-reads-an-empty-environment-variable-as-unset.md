---
id: lesson-672-click-reads-an-empty-environment-variable-as-unset
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, make, click, testing]
---

# click reads an empty environment variable as unset

**Context**: `make mutate` hands FROM and TO to the toolkit through the environment, so quotes need no escaping (#2104). A mutation that deletes text is spelled `TO=`.

**Problem**: click resolves an option's `envvar` only when the value is non-empty, so `TO=""` reaches typer as no value at all and the command refused with `Missing option '--to'` (#2839). Deleting a guard line, the commonest mutation there is, could not be expressed. The proof of the fix hit a second trap: the test that renders the recipe with `make -n` inherited the outer `make mutate`'s command line through `MAKEFLAGS`, `TO=` included, so its "TO undefined" case saw TO defined and the baseline went red.

**Solution**: the recipe passes `--to "$$TO"` whenever TO is defined, empty included (`$(origin TO)` is `undefined` only when no one set it), and an undefined TO still refuses. `tests/test_mutate.py` holds both, and runs its inner make without `MAKEFLAGS`, `MFLAGS`, `MAKELEVEL` or `MAKEOVERRIDES`.

**Rule**: an environment variable cannot carry an empty value to a click option; where empty is meaningful, pass it as an argument. A test that runs `make` must drop `MAKEFLAGS`, or an outer make decides its command line.

**Tags**: `#make` `#click` `#mutate` `#issue-2839`
