---
id: lesson-432-a-guard-that-cannot-tell-a-warning-from-an-instance
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: toolkit-tooling
tags: [kubelab, make, guards, tests, documentation]
---

# A file that contains its own explanation cannot be edited by a pattern that matches the explanation

**Context**: eight `make` targets used `$(or $(ENV),prod)`, which cannot reach
its fallback because `ENV ?= dev` is set globally — so each promised prod and ran
against dev (#1644). The fix was mechanical: replace the idiom everywhere.

**Problem**: the first attempt was a blind string replace, and it made **nine**
substitutions where eight were expected. The ninth was this comment, on the one
target that had already been fixed:

```make
# `$(or $(ENV),prod)` would not do it -- ENV defaults to `dev` globally
# (below), so an unset ENV never reaches `or` empty.
```

It became a claim that the *fix* does not work. The replace was correct about
every recipe line and wrong about the only line that explained why the replace
was needed — because a warning quotes the thing it warns about, so it matches
the pattern that hunts for instances of it.

Caught by reading the diff, not by running anything. Nothing would have failed:
Make ignores comments, every test stayed green, and the file would have shipped
carrying documentation that argued against its own code.

**Solution**: the guard that replaced the eight edits inspects **recipe lines
only** — lines beginning with a tab, which is what Make expands — and never
comments.

```python
def _recipe_lines() -> list[tuple[int, str]]:
    return [
        (n, line)
        for n, line in enumerate(MAKEFILE.read_text().splitlines(), start=1)
        if line.startswith("\t")
    ]
```

Without that restriction the guard would go red on the comment that documents
the bug, and the only ways to make it green would be to delete the explanation
or to add an exemption for it.

**Rule**: **a guard that cannot tell a warning from an instance forbids the
repo from documenting its own bug.** Any check that matches on the *text* of a
defect will also match every place that text is quoted in order to be explained
— comments, lessons, test fixtures, PR bodies stored in the tree. Decide which
positions are executable and scope the guard to those, at the moment you write
it. The alternative is discovering it as a red build on a docs commit, where the
cheapest fix is to stop writing the docs.

Corollary for the edit itself: **a `sed` over a file that contains its own
explanation rewrites the explanation.** Count the substitutions and check the
number against what you expected — the surprise was one integer, and it was the
whole finding.

**Why this is not [lesson-416](../ci-automation/lesson-416-a-guard-the-guard-must-assert-on-the-derived-artifact.md)**:
that one is about a guard whose expectation was empty, so it matched
everything and asserted nothing. This is the opposite failure — an expectation
that is exactly right about the population it was aimed at, and includes a
member that must be exempt for the population to remain describable.

**Tags**: `#make` `#guards` `#documentation` `#issue-1644` `#pr-1647`
