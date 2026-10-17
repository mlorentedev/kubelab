---
id: lesson-452-a-partial-view-of-a-corpus-answers-like-the-whole-corpus
type: lesson
status: active
created: "2026-09-06"
owner: manu
category: process-method
tags: [kubelab, process-method, memory, context, handoff, lessons-index]
---

# A partial view of a corpus answers exactly like the whole corpus, and it caught this lesson three times while it was being written

**Context**: Housekeeping on `MEMORY.md`, the per-project index loaded into
every session at startup, followed by filing a lesson about what that
housekeeping found — and then the review of that lesson. Three questions were
asked about a corpus in one evening. Each was answered by something that only
looked like the corpus, and the third one landed on this file.

**Problem**:

**First: an index that loads truncated loses its newest entries.** Sessions
append to `MEMORY.md` — each writes its handoff as a new `### thread:` block at
the end. Seventeen threads had accumulated, 285 lines and 68 KB, and the
session-start banner said:

```
WARNING: MEMORY.md is 256 lines and 61KB. Only part of it was loaded.
```

The obvious reading is a proportional loss, which sounds survivable. It is not
proportional. Truncation drops from the **end**, and the end is where the
**newest** threads live, because the file is written by appending. The sessions
most likely to matter — yesterday's work, the branch still open, the deploy
still half-applied — are exactly the ones cut, while five-day-old threads at the
top load in full every time. And a knowledge index has no failure signal: a
thread a session cannot see and a thread that was never written are
indistinguishable from inside that session. The banner had been firing for days,
read as a tidiness nag rather than as data loss.

**Second: "the next free lesson number", answered from a checkout.** Filing the
lesson above meant picking a number. The check looked careful — every open pull
request branch was enumerated through `git ls-tree` on its `origin/` ref, and
every local worktree was searched:

```
$ ls docs/lessons/*/lesson-*.md | sed 's/.*lesson-\([0-9]*\)-.*/\1/' | sort -n | tail -3
439
440
441
```

`442` was free, and `442` collided immediately. That `ls` read the **working
tree** of a checkout sitting at `591d040a`, and `origin/master` was already five
lessons further along at `446`. The branches were checked against refs; master
was checked against a stale directory. A `git fetch --prune` had run earlier in
the session, which updated the refs and — correctly, and invisibly — left the
working tree alone.

The output is the tell that there is no tell: `441` is a perfectly plausible
answer. Nothing about it says "this is what the corpus looked like an hour ago".

**Third, while this file sat in review: the number went stale a second time, and
not by anyone's mistake.** This lesson was filed as `447`, correctly, against a
`master` that ended at `446`. Someone then pressed GitHub's **Update branch**
button on the pull request:

```
$ git log -1 --format='%h %cn <%ce> | %s' origin/docs/lesson-truncated-index-drops-newest
7d48c571 GitHub <noreply@github.com> | Merge branch 'master' into docs/lesson-truncated-index-drops-newest
```

That merge brought in `identity-secrets/lesson-447`, which had landed on master
in the meantime, and the branch then held two lesson `447`s. The reviewer
reported it as a Major before any human noticed. Renumbered to `452`.

Note what this instance adds: the first two were a stale view being *read*. This
one is a correct view **going stale underneath a merged artifact** — the branch
was right when pushed, and a server-side merge made it wrong without any local
event to notice. It is the third route named in `#1678`, and neither local hook
stage can reach it.

**Solution**:

For the index: condense oldest-first, against the durable record rather than
deleting. Every thread block ends with a `Journal:` pointer into
`10_projects/<project>/sessions/`, so the narrative already lives somewhere
permanent. Ten threads dated 2026-09-04 or earlier became one line each; seven
from 09-05/09-06 stayed whole. 285 lines / 68 KB → 202 / 36 KB. **Before
removing anything, every pointer was resolved:**

```
$ grep -o 'sessions/[a-zA-Z0-9._@-]*\.md' MEMORY.md | sort -u | while read -r j; do
    [ -f "10_projects/kubelab/$j" ] && echo "  OK   $j" || echo "  MISSING $j"
  done
```

17 of 18 resolved, and the one that did not belonged to a thread being *kept* —
so nothing was condensed against a journal that was not there. That check is
what makes "nothing is lost" a measurement instead of an assurance.

For the number: ask the ref, never the directory.

```
$ git ls-tree -r --name-only origin/master -- docs/lessons \
    | grep -o 'lesson-[0-9]*' | sed 's/lesson-//' | sort -n | tail -1
446
```

The collision itself was caught by `test_no_two_lessons_share_a_number`, and by
the local gate added the same day (#1714) which refuses to recount a corpus with
a duplicated number instead of quietly making its counter correct. The guard
worked. What failed was upstream of it — the choice the guard exists to protect.

**Rule**: **Ask the source, not a copy of it.** A truncated load, a stale
working tree, a cached listing: each returns a well-formed answer about a subset
and says nothing about being a subset. When a question is about a *corpus* —
what exists, what is taken, what is the newest — address the thing that is
authoritative for it (`origin/master`, the ref; the file, not the loaded
excerpt), because the difference is invisible in the result and only visible in
the query.

**And asking the source is not a one-time act.** The third instance was answered
correctly at the moment it was asked; a server-side merge invalidated it
afterwards, with nothing local to notice. For anything that stays open — a pull
request, a long-lived branch — the freshness of the answer expires, so the check
belongs at the moment of *merging*, not only at the moment of authoring. That is
why the counter guard is derived by a hook and asserted again in CI rather than
computed once by the author: *"derived once is not derived"* (`#1649`).

Three corollaries:

- **"Only part of it was loaded" is a data-loss warning, not a size warning.**
  Read any truncation notice as a question about *which* part, and answer it
  before deferring. When the surface is written by appending, the answer is
  always "the newest".
- **A file that documents its own maintenance ritual and has no command that
  performs it will not be maintained.** `dotf mem` has `handoff-write`, which
  writes one thread, and nothing that condenses the rest. `MEMORY.md`'s own
  header — *"Older threads are condensed to one line each"* — had been true and
  unexecuted for weeks. [[lesson-365]] applied to an index instead of a hook.

**Tags**: `#memory` `#context` `#handoff` `#lessons-index` `#pr-1678`
