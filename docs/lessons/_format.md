# Lesson format

One lesson per file: `docs/lessons/<category>/lesson-NNN-<slug>.md`.

Numbers are assigned in the order lessons were filed and never change, so a
citation stays valid. A new lesson takes the next free number — do not renumber
to keep the set sorted, the indexes do the sorting.

## Front-matter (required)

```yaml
---
id: lesson-NNN-<slug>        # must equal the filename without .md
type: lesson
status: active
created: "YYYY-MM-DD"        # when the lesson was learned, not when filed
owner: manu
category: <one of the directories under docs/lessons/>
tags: [kubelab, <category>, ...]
---
```

## Body

The heading is the lesson's claim, stated as a finding rather than a topic —
"A LimitRange can *reject* pods", not "About LimitRanges". Then four sections:

```markdown
# <the claim>

**Context**: What was being done.

**Problem**: What went wrong, or what turned out to be true.

**Solution**: How it was resolved, with the command or diff that proves it.

**Rule**: The pattern to follow next time — the part worth reading alone.

**Tags**: `#topic` `#pr-NNNN`
```

**Protocol**: write the lesson in the session that produced it. A correction
noticed and not written down is the one that recurs.

After adding a file, add its row to the category's `_index.md` and bump the
count in [`_index.md`](_index.md).
