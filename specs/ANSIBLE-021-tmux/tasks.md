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
- [ ] Run `make provision NODE=ace2 ENV=staging` (or equivalent) — verify idempotent, `tmux` installed (homelab-on + ts-bridge)
- [ ] Run on remaining hosts: ace1, rpi4, rpi3, beelink, vps, aws1
- [ ] Execute smoke loop: `for h in ace1 ace2 rpi4 rpi3 beelink vps aws1; do ssh "$h" tmux -V; done` — capture output

## Closing

- [ ] All hosts return `tmux 3.x` (or similar)
- [ ] Jetson explicitly excluded — confirm
- [ ] Diff is a single-line role change + zero changes elsewhere (no scope creep)
- [ ] `verification.md` filled in (or marked deferred — low risk)
- [ ] PR opened; close #814 on merge — built-in workflow sets bitácora Done (ADR-018, no more `11-tasks.md`)
