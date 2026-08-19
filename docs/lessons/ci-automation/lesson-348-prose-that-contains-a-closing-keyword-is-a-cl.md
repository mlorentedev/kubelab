---
id: lesson-348-prose-that-contains-a-closing-keyword-is-a-cl
type: lesson
status: active
created: "2026-08-18"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# Prose that contains a closing keyword is a closing keyword

**Context:** PR #1153 ported two acceptance criteria into the BACKUP-044 spec. Its body carried a section listing what the PR deliberately did *not* do, whose first bullet was titled **"No `Closes`"** and read:

> BACKUP-044 is still in flight; the spec gate this repo gained in #1143 would rightly refuse a PR that closed #1056 without archiving it.

`Spec archive gate` failed: *"This PR closes a spec's issue without archiving the spec."*

**Problem:** the gate was right, and the sentence asserting there was no closing reference is what created one. **GitHub's closing-keyword parser is not context-aware** — it matches `closed #1056` wherever it appears in a PR body, including inside prose explaining that no such reference exists. Verified at the source rather than inferred:

```bash
gh api graphql -f query='{repository(owner:"mlorentedev",name:"kubelab"){
  pullRequest(number:1153){closingIssuesReferences(first:10){nodes{number state}}}}}'
# -> [{"number": 1056, "state": "OPEN"}]
```

Merging as written would have closed BACKUP-044's tracking issue with **32 of its 42 tasks unchecked**. Nothing in the rendered PR announces this; the link lives in the sidebar, and the body says the opposite in bold.

**Solution:** GitHub's keywords are `close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, `resolve`/`resolves`/`resolved`. The gerund is not among them, so the fix was one word:

```diff
-would rightly refuse a PR that closed #1056 without archiving it
+would rightly refuse a PR closing #1056 without archiving it
```

```bash
# after the edit — must come back empty
gh api graphql -f query='...closingIssuesReferences...'   # -> []
```

Note `gh pr edit` cannot apply this in kubelab — it aborts on a Projects-classic field and changes nothing (lesson-002, lesson-338). Use `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f body=...`.

**Measured while writing this lesson**, because the PR carrying it reproduced the bug in its own body:

- **An HTML entity does not defeat the parser.** The body quoted the offending sentence as `clos&#101;d #1056`, expecting the entity to break the keyword. `closingIssuesReferences` returned #1056 anyway — GitHub decodes entities before matching. Replacing the entity with zero-width separators (U+2060 inside the word, U+200B before the `#`) *did* empty the reference. **The general rule, which matters more than either technique: an escape that exists only in the source text is defeated by anything that normalises before matching.** Zero-width separators work because they survive rendering — they are still there when the parser looks. Reach for the gerund first anyway; an invisible character in prose is a landmine for whoever edits the line next.
- **In this repo, a closing keyword in a commit message is inert — the PR body is the only text that reaches master.** The commit for this lesson still contains `closed #1056` verbatim, and after the body was corrected the query came back empty. `gh api repos/<owner>/<repo>` reports `allow_merge_commit: false`, `allow_rebase_merge: false`, `squash_merge_commit_title: PR_TITLE`, `squash_merge_commit_message: PR_BODY`. Individual commit messages are discarded by the squash, so they never land on the default branch. **This makes the PR body doubly load-bearing**: it decides what the merge closes *and* it becomes the master commit message. A repo that allowed merge commits would have the opposite exposure, so check the setting before carrying this conclusion elsewhere.

**Rule:**

- **Never write an issue number after a closing keyword unless you mean it.** To *discuss* one, use a non-keyword form (`closing #N`, `a PR that closes it`) or drop the number. Prose about a closing reference is indistinguishable from one.
- **Verify at GitHub, not by reading the body.** `closingIssuesReferences` is the only authority on what a merge will close. A body that says "No `Closes`" is a claim; the query is the measurement — and a self-grep of your own draft is not, as this lesson's PR proved by passing its own scan and closing an issue anyway.
- **Re-query after editing — the first read can be stale by seconds.** Immediately after the `PATCH`, the query still returned #1056 and the fix looked ineffective; seconds later it was empty. A measurement taken too *early* is the mirror of the stale-baseline trap in lesson-307, and fails the same way: a correct reading of the wrong moment.
- **A gate that fires on `edited` earns it in both directions.** A body edit can turn a passing PR into a closing one without touching a file — and here it did the reverse, re-running the gate unprompted on the fix.
- **A word-boundary scanner is not the same parser as GitHub's.** The gate's own `\bclosed\b` matches inside `auto-closed`, because the hyphen is a word boundary — that is a property of `spec_gate.py`'s scanner, measured there. Whether GitHub also parses `auto-closed #N` as a closing reference has **not** been tested. Attribute each behaviour to the parser it was measured against.

The gate caught its own author: the same session had written `spec_gate.py` and its `_CLOSING_KEYWORDS` the day before. Worth recording because it inverts the week's pattern — six consecutive findings were controls that *could not* exhibit the failure they guarded (lesson-004 among them). This one could, did, and was correct.

**Tags:** `#github` `#pr` `#spec-gate` `#gotcha` `#pr-1153`
