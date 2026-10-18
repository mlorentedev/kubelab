#!/bin/bash
set -eu

# ---------------------------------------------------------------------------
# Guard: never recreate a branch whose pull request is already merged.
#
# lesson-402 records that a push to a merged PR's branch RECREATES it and exits
# 0 -- the commit lands on a branch no PR tracks, and nothing says so. The lesson
# was written, was in the session's own opening notes, and the trap was still
# sprung TWICE in one evening (2026-08-31). That is lesson-365's point exactly:
# a written reminder fails precisely when the situation arrives. So it becomes a
# mechanism.
#
# The signal is cheap and exact. A branch with no remote ref is either brand new
# or one GitHub deleted after merging; `gh pr list --state merged --head` tells
# the two apart with certainty rather than heuristics.
#
# WHEN gh CANNOT ANSWER, THIS ALLOWS THE PUSH. Offline, unauthenticated, or gh
# not installed -- all warn and continue. Stated rather than silent, because
# "fail open" is usually the wrong default and here it is deliberate: this guard
# prevents an orphaned commit, not a security property, and a hook that blocks
# every push whenever the network is down would be disabled within a week. A
# guard that gets removed protects nothing.
# ---------------------------------------------------------------------------
check_merged_branch() {
  local remote="${1:-origin}"
  local local_ref local_sha remote_ref remote_sha branch merged

  command -v gh >/dev/null 2>&1 || {
    echo "[WARN] gh not installed — skipping the merged-branch check"
    return 0
  }

  while read -r local_ref local_sha remote_ref remote_sha; do
    # A deletion (`git push --delete`) sends an all-zero LOCAL sha. Deleting a
    # merged branch is exactly the cleanup this guard wants to encourage.
    case "$local_sha" in *[!0]*) ;; *) continue ;; esac

    # A non-zero REMOTE sha means the branch still exists there: an ordinary
    # update, not a recreate. Only the zero case can resurrect a deleted branch.
    case "$remote_sha" in *[!0]*) continue ;; esac

    case "$local_ref" in refs/heads/*) branch="${local_ref#refs/heads/}" ;; *) continue ;; esac

    # MERGED *or* CLOSED, per TOOL-045 AC1. Merged is the common case (GitHub
    # deletes the branch on merge); closed-and-deleted is rarer and identical in
    # consequence -- the commit lands where no PR is looking.
    merged=$(gh pr list --head "$branch" --state all --json number,state \
      --jq 'map(select(.state == "MERGED" or .state == "CLOSED")) | .[0] | select(.) | "\(.number) \(.state)"' 2>/dev/null) || {
      echo "[WARN] could not ask GitHub about '$branch' — skipping the merged-branch check"
      continue
    }

    if [ -n "$merged" ]; then
      set -- $merged
      echo "[ERROR] '$branch' belongs to PR #$1, which is already $2."
      echo "        Pushing would recreate the deleted branch and leave your commit"
      echo "        on a branch no PR tracks (lesson-402). Instead:"
      echo ""
      echo "          git checkout -b <new-branch> ${remote}/master"
      echo "          git cherry-pick <your commits>"
      echo ""
      echo "        Override with --no-verify only if you mean to reopen that branch."
      return 1
    fi
  done
  return 0
}

# stdin carries the ref updates and is consumed by the check above; the remote
# name is git's first argument.
check_merged_branch "${1:-origin}"

# ---------------------------------------------------------------------------
# Guard: the lesson indexes must be in order and the corpus free of hazards.
#
# Until #2525 the indexes stated lesson counts, and this guard existed for
# them; the indexes no longer state any count, so a merge has nothing to race
# on. What remains is row order and the hazards below. The history stays
# because it explains why a MERGE needs a push-time check at all.
#
# The pre-commit hook checks the indexes when a lesson is WRITTEN. It structurally
# cannot see a lesson that arrived by MERGE: measured 2026-09-05, git does not
# run pre-commit for a merge that resolves cleanly -- `Merge made by the 'ort'
# strategy`, no hook output, 433 files and 432 declared. That is the route all
# four counter collisions took (#1649).
#
# So the commit-time hook catches the author and this catches the LOCAL merger.
#
# It does not catch the merger who never merges locally. GitHub's "Update
# branch" button merges master in on GitHub's servers: no local commit, no
# local push, so neither stage is reached and the stale counter goes straight
# to CI. Measured 2026-09-05 on #1675 (`7cc5b6fc`) and #1665 (`7d489552`).
# An earlier version of this comment claimed the pair left CI as nothing but a
# late backstop. For that third route CI is the only thing left, and calling it
# a net is generous: `Tests` is not a required check on master, so the guard
# goes red and the merge stays available. It surfaces the defect; it does not
# stop it. That is why #1678 exists. See `.pre-commit-config.yaml` for how to
# tell the routes apart after the fact (read the committer, not the message).
#
# --check, never --fix: rewriting files mid-push would leave the working tree
# ahead of what is being pushed.
#
# The exit code is read rather than merely tested, because the `--fix` hint
# below is WRONG for two of the three failures and following it there makes the
# defect invisible (#1678 AC5). Exit 1 is rows out of order, which --fix is
# exactly right for. Exit 2 is a hazard -- a duplicated lesson number, or a
# lesson that HEAD has and the tree does not -- where a rewrite reports success over a
# broken corpus. Exit 3 is CANNOT CHECK: the question went unanswered,
# and an unanswered question is not a pass.
#
# Run ONCE and show the output, instead of running silently and then again to
# display it: the second run can disagree with the first, and the operator would
# be reading a different execution from the one that decided their push.
# ---------------------------------------------------------------------------
# Preflight: can the tool run AT ALL in this checkout? A fresh worktree has no
# venv, so `poetry run -- toolkit` dies with PackageNotFoundError before the
# check starts -- and an uncaught Python exception exits 1, the SAME code the
# checker uses for "rows out of order". Measured 2026-09-06 on a canon-refresh
# worktree: the hook printed the --fix remedy for an index that was correct.
# Ask the cheap question first, in a function so the test suite can exercise
# it with a fake `poetry` on PATH, the way check_merged_branch is tested.
toolkit_can_run() {
  poetry run -- python -c "import toolkit" >/dev/null 2>&1
}
if ! toolkit_can_run; then
  echo ""
  echo "[ERROR] toolkit cannot be imported in this checkout, so the lesson indexes"
  echo "        were NOT checked -- and an unanswered question is not a pass."
  echo ""
  echo "        Fresh worktree or new machine: run \`poetry install\` here and push again."
  echo "        Do NOT run --fix: it would rewrite indexes nobody has checked."
  exit 1
fi
lessons_rc=0
poetry run -- toolkit tools lessons-index --check || lessons_rc=$?
if [ "$lessons_rc" -ne 0 ]; then
  echo ""
  if [ "$lessons_rc" -eq 1 ]; then
    echo "[ERROR] Lesson index rows are out of order (newest first, #1912)."
    echo ""
    echo "        Usually a merge or a hand edit placed a row; --fix reorders it."
    echo ""
    echo "          toolkit tools lessons-index --fix && git commit -a --amend --no-edit"
  elif [ "$lessons_rc" -eq 2 ]; then
    echo "[ERROR] The lesson corpus is not in a state where a rewrite is safe."
    echo ""
    echo "        The remedy is the one printed above, which is specific to what was"
    echo "        found. Do NOT reach for --fix here: it would report success and"
    echo "        leave the defect in place, which is the trap this guard exists"
    echo "        to close. See #1678 AC5."
  else
    # Exit 3 gets its own words because exit 2 prints a per-hazard remedy and
    # this does not -- it prints only why the question went unanswered. Pointing
    # the operator at "the remedy above" when no remedy was printed sends them
    # looking for text that is not there.
    echo "[ERROR] The lesson corpus could not be checked, and that is not a pass."
    echo ""
    echo "        The reason is printed above; nothing about the corpus has been"
    echo "        verified either way. Make the question answerable (git on PATH, run"
    echo "        from inside the repository) and push again. --fix is not the answer"
    echo "        here either: it would rewrite indexes nobody has checked."
  fi
  echo ""
  exit 1
fi

echo "[INFO] Running pre-push checks..."
# `set -e` already aborts on a non-zero exit, so the old `status=$?` branch below
# this line was unreachable. Kept explicit instead of implicit: a lint failure
# should say why the push stopped.
if ! make lint; then
  echo "[ERROR] Linting failed. Push aborted."
  exit 1
fi
echo "[SUCCESS] All checks passed. Proceeding with push."
