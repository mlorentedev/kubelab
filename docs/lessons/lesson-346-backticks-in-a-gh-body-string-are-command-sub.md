---
id: lesson-346-backticks-in-a-gh-body-string-are-command-sub
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, shell, zsh, gh-cli, quoting, gotcha, durable-record]
---

# Backticks in a gh --body string are command substitution, and they delete your text silently

**Context:** Posting a long, code-formatted comment to a GitHub issue with `gh issue comment --repo X --body "...long markdown with `identifiers` in backticks..."` from zsh. Several earlier comments in the same session had used `--body "$(cat <<'EOF' ... EOF)"` and were fine.
**Problem:** Backticks inside double quotes are command substitution in every POSIX-ish shell. The shell ran `sqlite3 .backup`, `gravity.db`, `pihole -g` and `pihole-FTL.db` as commands, discarded the "command not found" output, and substituted empty strings. The comment posted successfully with four identifiers deleted, leaving two of its numbered points as sentences like "Four live SQLite databases need , not a file copy". The only visible signal was four "command not found" lines in the tool output, which are easy to read as noise from a wrapper rather than as evidence that the payload was mutated. Nothing failed — exit code 0, comment URL returned, durable record corrupted. This is worse than a crash: the damage lands in a permanent artefact that other people and future sessions read, and re-reading the source string in the transcript shows the *correct* text, so the error is invisible from the side you are most likely to check.
**Solution:** Pass any body longer than a sentence via `--body-file <path>`, writing the file with a real file-writing tool first. A `<<'EOF'` heredoc with a quoted delimiter is also safe, and that is why the earlier comments survived — the quoted delimiter suppresses all expansion, and command substitution output is not re-scanned. To repair an already-posted comment: `gh api -X PATCH repos/OWNER/REPO/issues/comments/<id> -F body=@file` (the `-F ...=@file` form reads the file, `-f` would not). Add a one-line note in the edited comment saying what was restored, so the edit history is not mistaken for a change of substance. General rule: when a command both interpolates a shell string and produces a permanent side effect, verify the artefact after writing it rather than trusting the exit code — read back the first few lines of what actually landed.
**Tags:** `#shell` `#zsh` `#gh-cli` `#quoting` `#gotcha` `#durable-record`
