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

echo "[INFO] Running pre-push checks..."
# `set -e` already aborts on a non-zero exit, so the old `status=$?` branch below
# this line was unreachable. Kept explicit instead of implicit: a lint failure
# should say why the push stopped.
if ! make lint; then
  echo "[ERROR] Linting failed. Push aborted."
  exit 1
fi
echo "[SUCCESS] All checks passed. Proceeding with push."
