# Run 2026-10-18-bug-sweep

**Verdict:** ended expiry after 2 iterations / ~8h: 2 done, 0 parked, 1 merged, 1 unmerged. Nothing irreversible is waiting on you; #2516 needs master green first.

## Waiting on you
- #2516 (dev Compose Grafana session bound, closes #2415): ready, Tests green except three lesson-corpus-count tests that fail on master itself (index says 598, 599 files; class tracked in #2525). The fix is peer PR #2524, blocked. After #2524 lands: merge master into the branch, wait for Tests, then land under the grant. PR-Agent reviewed it twice (findings applied, triage comment posted; last review "No major issues"). Head `719d9030`.
- PRs awaiting triage, not mine: #2464, #2463, #2457.

## Landed
- #2490 `ad45bb6d` (closes #2419): test holding Grafana's three OAuth URLs to each overlay's Authelia, mutation-proven.

## Corrections to disclose
- I merged #2490 as "unreviewed" (label plus rationale) because CodeRabbit and Codex had hit quotas and the PR-Agent `review` run showed `pending`. That run completed after the merge with "No major issues". A correcting comment is on the PR. Same mistake caught before merge on #2516 (label withdrawn). Rule for the lane: `pending` is slow, not absent; wait for it.

## Queue notes
- First pass ended queue-empty because I filtered the board's Backlog by type; the operator pointed out quick wins live in open issues outside it (565 open). Envelope widened to open bug/chore/debt issues (commit 33ab05c3).
- Next candidates read but not started: #2308 (TOOL-119 spec guard), #2447 (totalServices derived), #2377 (Authelia deprecated keys). Not eligible: #2136 (changes the Docker pool on every node).
- Host: wake-lock via caffeinate for the window.
