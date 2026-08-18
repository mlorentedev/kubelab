---
id: lesson-342-a-verification-loop-that-skips-on-error-repor
type: lesson
status: active
created: "2026-08-09"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# A verification loop that skips on error reports success — the failure hides behind the skip

**Context:** Closing out a two-session day on kubelab. Three branches with open PRs, and a parallel session kept advancing `master`, so I wrote a shell loop to check each still merged cleanly: `git merge-base` + `git merge-tree`, piped to `grep -q '^<<<<<<<'`, printing "clean" when grep found nothing.

**Problem:** One branch printed "clean" because the check could not run. `git rev-parse` had failed with "Not a valid object name" — that branch was gone from origin — so `git merge-base` produced nothing, `git merge-tree` never executed, and grep searched the *error text*, found no conflict markers, and returned non-zero. The loop reported the most reassuring possible answer for the one branch it knew least about.

Every guard was individually reasonable; the composition inverted the result. This is the same defect shape as three others recorded the same day — `tls: {}` as a no-op strategic merge, acceptance criteria whose strings could never fail, a drift gate that does not compare the field it claims to. Sharper here, because I produced it while actively writing lessons about that exact pattern. Being able to name a failure mode does not stop you producing it: the discipline has to live in the check's construction, not in the author's attention.

**Solution:** Verify the precondition first and say so explicitly — `git rev-parse --verify --quiet` on the ref, and if missing print `CANNOT CHECK` and continue, never a verdict. The corrected run produced the truth: one branch had merged and been auto-deleted, another had three `Merge branch 'master'` commits layered on top of mine. Both benign, but the original loop would have had me report the wrong thing.

**Rule:** A check must distinguish **three** outcomes, not two — pass, fail, and could-not-run — and could-not-run must never render as pass. In shell specifically, absence of a pattern is not evidence when the command producing the text may not have run: validate the input to the grep, not only its output.

**Tags:** `#verification` `#shell` `#git` `#checks-that-cannot-fail` `#parallel-sessions`

---
