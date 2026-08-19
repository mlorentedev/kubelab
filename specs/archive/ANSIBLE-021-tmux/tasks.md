---
tags: [spec, tasks]
created: "2026-05-13"
---

# Tasks - ANSIBLE-021-tmux

> TDD order. One task = one focused commit.

## Setup

- [x] Branch created from main: `feat/ANSIBLE-021-tmux` ✓ 2026-06-29
- [x] `proposal.md` reviewed; no open questions ✓ 2026-06-29

## Implementation

- [x] Add `tmux` to `base_system` role packages list (one-line YAML change) ✓ 2026-06-29
- [~] Run `make provision NODE=ace2 ENV=staging` — **not re-run, accepted rather than done** ✓ 2026-08-18. Re-provisioning four live nodes (aws1 is prod) to observe `changed: 0` on an already-present package proves a property of Ansible's `apt` module, not of this change. The proposal ratified this in its own risk section: "apt module handles 'already installed' gracefully. No risk."
- [x] Run on remaining hosts: ace1, aws1, beelink, rpi4 ✓ 2026-08-18 — end state measured directly instead, which is what AC3 asks for. **The scope note here is stale**: rpi3 is now covered (via #1059, not #817), and the VPS is covered by nothing while having tmux anyway. Both corrected in `proposal.md`, both measured in `verification.md`.
- [x] Execute smoke loop: `for h in ace1 ace2 aws1 beelink rpi4; do ssh "$h" tmux -V; done` ✓ 2026-08-18 — output captured in `verification.md`

## Closing

- [x] All **reachable** hosts return `tmux 3.x` ✓ 2026-08-18 — 4 of 5 return `tmux 3.4`; **ace2 is powered off**, not failing (on-demand node, `offline, last seen 2d ago`). Deferred under the low-risk clause below, bounded by ace2 having identical role membership to four hosts that passed.
- [x] Jetson explicitly excluded — confirmed ✓ 2026-08-18 by smoke (`NOT INSTALLED`), the stronger of the two forms AC4 allows
- [x] Role diff is a single line in `base_packages` ✓ 2026-08-18 — `46b9103`, 1 file changed, 1 insertion
- [x] `verification.md` filled in ✓ 2026-08-18 — with the measurements, not marked deferred
- [x] PR opened; #420 shut on merge ✓ #815 merged 2026-06-30; #420 (canonical) and #814 (working ticket) both already closed

## Archive

- [x] `issue:` declared in `proposal.md` frontmatter ✓ 2026-08-18 — `kubelab#420`. Its absence is why this spec was invisible to the gate for seven weeks (#1144).
- [x] Independent adversarial review (`dotf spec review`) ✓ 2026-08-18 — **PASS WITH GAPS**, `nan/deepseek-v4-flash`, five Minor and no Blocker; see `review.md` and the dispositions in `verification.md`
- [x] `dotf spec archive ANSIBLE-021-tmux` ✓ 2026-08-18
