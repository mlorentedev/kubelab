---
id: lesson-365-a-lesson-with-no-mechanism-is-a-reminder-and-i-broke-mine-three-times
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: process-method
tags: [kubelab, process-method, git, verification, mutation-testing, uncommitted-work]
---

# A lesson with no mechanism is a reminder, and I broke my own three times in one session

**Context**: [`lesson-344`](lesson-344-a-negative-control-mutates-real-code-so-its-u.md) was
written on 2026-08-09 after `git checkout --` destroyed an uncommitted feature
during a mutation test. It is accurate, specific, and names the fix: *"git
checkout is not an undo, it is a reset to the last staged state, and its blast
radius is the whole file no matter how small the experiment was."*

On 2026-08-22 I destroyed uncommitted work with `git checkout --` **three
times** — twice in `toolkit/cli/infra.py`, the same file lesson-344 was written
about, and once in the `node_backup` templates. Every time, restoring after a
mutation test. Every time, the exact scenario the lesson describes.

**Problem**: The lesson had no mechanism behind it. Nothing runs it, nothing
checks it, nothing fires when the pattern appears. It is prose in a directory of
360 other prose files, and it is cited by exactly one line: its own index row.

That makes it a **reminder**, and a reminder only works on someone who happens
to recall it at the moment it applies. Mutation testing is precisely when you do
not: attention is on whether the guard went red, and the restore feels like
bookkeeping rather than the risky step it is.

The failure is worse than a first-time mistake, because the knowledge existed
and was written down correctly. Writing it down was treated as the fix. It was
not — it was the *record* of a fix that never got built.

**Solution**: The mutation-test loop now commits before it mutates:

```bash
git add -A && git commit -q -m "wip: <what is being proven>"
# mutate, observe red, then:
git checkout HEAD -- <file>          # safe BY CONSTRUCTION now
```

`git checkout HEAD -- <file>` after a commit restores to work that is already
saved. The dangerous form and the safe form are the same command; what differs
is whether the index holds anything worth losing. Committing first removes the
distinction instead of asking anyone to remember it.

Three markers that this had gone wrong, each of which I hit at least once:

- A test that passed a minute ago failing with `AttributeError` or `NameError`
  on a symbol you just wrote.
- `git status` showing a file as unmodified when you know you changed it.
- A failure count exactly equal to the size of a file you just added
  (lesson-344's own tell).

**Rule**: **A lesson without a mechanism decays into a reminder, and a reminder
fails exactly when the situation it warns about arrives.** When a lesson is
written, ask what would *enforce* it — a guard, a hook, a changed default, a
step folded into the loop it applies to. If the honest answer is "nothing, the
next person has to remember", say so in the lesson, because that is a different
and weaker claim than "this is handled".

The corollary this session actually paid for: **when you break the same lesson
twice, stop and change the procedure.** The second occurrence is data about the
mechanism, not about your attention. I recognised it on the third.

**Tags**: `#git` `#mutation-testing` `#uncommitted-work` `#knowledge-decay` `#pr-1230`
