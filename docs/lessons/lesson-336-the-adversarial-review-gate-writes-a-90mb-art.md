---
id: lesson-336-the-adversarial-review-gate-writes-a-90mb-art
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, git, spec-driven-development, adversarial-review, gitignore, cli-034, gotcha]
---

# The adversarial-review gate writes a ~90MB artifact into the spec folder, untracked and unignored

**Context:** `dotf spec review` (CLI-034's archive gate) writes two files beside the spec: `review.md`, the verdict, and `review-transcript.jsonl`, the reviewer's full tool-call log. The pool's own documentation argues the transcript is essential — "the verdict records what a reviewer concluded and the transcript is the only record of how".

**The trap:** for one spec, that transcript was **91 MB**, because it embeds the content of every file the reviewer read. It lands inside `specs/<id>/`, is not gitignored, and no archived spec in `specs/archive/` contains one — so the house convention of not committing them existed only as an accident of nobody having tried. A routine `git add -A` before the archive commit stages it silently; GitHub warns above 50 MB and rejects above 100 MB, so the failure surfaces at `git push`, after the commit, in whatever session is trying to close the spec.

Caught here only because the commit's file list was read before pushing.

**Fix:** ignore it explicitly, with the reasoning attached so the next reader does not "fix" the ignore by removing it:

```gitignore
# Adversarial-review transcripts (`dotf spec review`). The verdict in review.md
# IS committed; the transcript is the reviewer's full tool-call log and runs to
# ~90MB for one spec [...] Kept local as the record of HOW a verdict was
# reached; re-derivable by re-running the review.
specs/**/review-transcript.jsonl
```

**Rule:**
- **Any repo adopting the review gate needs this ignore before its first review, not after.** The artifact is produced by a tool the repo does not own, into a directory the repo does commit.
- **Read the file list of a commit that includes tool-generated artifacts.** `git add -A` after running an unfamiliar tool is where oversized and secret-bearing files enter history; the staged list is the last cheap checkpoint.
- **"No prior example has it" is not evidence of a convention** — it can equally mean the situation never arose. Here both readings looked identical until the file size was checked.

**Tags:** `#git` `#spec-driven-development` `#adversarial-review` `#gitignore` `#cli-034` `#gotcha`
