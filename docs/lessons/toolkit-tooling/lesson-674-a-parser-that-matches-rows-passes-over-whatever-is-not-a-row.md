---
id: lesson-674-a-parser-that-matches-rows-passes-over-whatever-is-not-a-row
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, lessons, git, guards]
---

# A parser that matches rows passes over whatever is not a row

**Context**: `toolkit tools lessons-index` orders each category's rows, and `tests/test_lesson_index_integrity.py` holds the rows to the files: every file has a row, every row has a file, no row twice. Both read an index by matching the lines shaped like a row.

**Problem**: A conflicted `_index.md` passes all of it (#1700, measured on #1696). Git's markers sit between two blocks of rows that are each well formed, and a marker line is not shaped like a row, so a row matcher never sees it. `--fix` reordered the rows across the markers and reported success, the row tests passed, and a `git commit -a` would have staged the markers behind a green suite. `check-merge-conflict` in pre-commit does not close this: it runs only while git records a merge or a rebase, so a conflicted cherry-pick or stash pop goes past it, and it says nothing to the deriver or the tests run by hand mid-merge.

**Solution**: `unmerged_indexes()` reads every index for the four markers git writes (`<<<<<<<`, `|||||||`, `=======`, `>>>>>>>` at column 0) and `hazards()` reports them before anything is written. The CLI exits 2, the hazard code, not the 1 of a row out of order, because the remedy differs: finish the merge, not reorder. The integrity test imports the same predicate, so a tree with markers is red.

**Rule**: A check that selects the lines it understands is silent about every other line. When a file must be wholly well formed, add one check over the whole file for the shapes that make it invalid, beside the checks over its parts.

**Tags**: `#lessons` `#git` `#issue-1700`
