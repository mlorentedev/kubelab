#!/bin/sh
# Conventional Commits gate for hand-written messages (CI-GATE-012, #1145).
#
# The rule applies to what a human types. It must NOT apply to the messages git
# writes itself: `git merge`, `git revert`, `git cherry-pick` and `git commit
# --fixup` all generate their own, none of which is Conventional, so without an
# exemption those four commands fail out of the box.
#
# Rejecting them protected nothing anyway — this repo is squash-merge only
# (`allow_merge_commit: false`), so a merge commit's message is discarded by the
# squash and never reaches master. The message that lands is the squash title,
# which is written by hand and still gated here.
#
# Worse than the friction: a refused merge commit leaves the merge *staged but
# uncommitted*. Git prints "Not committing merge", which reads as a failed
# operation when the merge in fact succeeded — inviting a `git reset` that throws
# away resolved conflicts.
#
# Detection is by git's own state, not by matching the prose. `commit-msg`
# receives ONE argument (the message file) and no source hint — verified, not
# assumed — so the reliable signal is the *_HEAD file git maintains while the
# operation is in flight. Matching "Merge "* instead would also exempt a
# hand-written "Merge strategy notes", which is exactly the case the gate exists
# for.
MSG_FILE=$1
MSG=$(cat "$MSG_FILE")
GIT_DIR=$(git rev-parse --git-dir)

# An in-flight merge / revert / cherry-pick: the message is git's, not the author's.
if [ -f "$GIT_DIR/MERGE_HEAD" ] || [ -f "$GIT_DIR/REVERT_HEAD" ] || [ -f "$GIT_DIR/CHERRY_PICK_HEAD" ]; then
  exit 0
fi

# `--fixup` / `--squash`: git generates these prefixes and an autosquash rebase
# consumes them, so they never survive into history under this name.
case "$MSG" in
  "fixup! "*|"squash! "*|"amend! "*) exit 0 ;;
esac

if ! echo "$MSG" | grep -Eq '^[a-z]+(\(.+\))?!?: .+'; then
  echo "[ERROR] Commit message must follow Conventional Commits format (e.g., 'feat: message', 'fix(scope): message', 'refactor!: breaking change')."
  echo "Commit message was: $MSG"
  echo "Please correct the commit message and try again."
  exit 1
fi
