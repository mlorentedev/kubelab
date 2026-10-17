---
id: lesson-537-keeping-both-sides-of-a-conflict-also-keeps-both-copies-of-a-line-that-must-exist-once
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, git, lessons-index]
---

# Keeping both sides of a conflict also keeps both copies of a line that must exist once

**Context**: Restacking three backup PRs (#2113, #2114, #2115), every rebase step
conflicted on the lesson indexes, because each branch adds a lesson. The
resolution kept both sides of each hunk, so that both new rows survived, and
then ran `lessons-index --fix` to recount.

**Problem**: The top-level `docs/lessons/_index.md` has one line that is not a
row: `N lessons, one file each.` It sits in the conflict hunk too, so keeping
both sides kept two copies of it, and on the top branch four. `--fix` then
rewrote every copy to the right count, `--check` passed, and so did the integrity
test, which read the first count it found. PR-Agent found the duplicate on #2114
by reading the diff. Nothing in the repository could have found it.

**Solution**: `_stated_count` in `tests/test_lesson_index_integrity.py` requires
exactly one summary line per index. Doubling the line in the top-level index, or
in a category index, turns the suite RED. The branches were repaired by
resolving the hunk to one line before `--fix`.

**Rule**: "Keep both sides" is right for lines that are a set (table rows) and
wrong for lines that are a singleton (a count, a heading, a version). Classify
the conflicting lines before choosing a resolution. A checker that only compares
values cannot see a repeated singleton, so check how many copies exist, not only
what each one says.

**Tags**: `#git` `#lessons-index` `#pr-2114`
