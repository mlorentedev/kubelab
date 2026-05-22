---
tags: [spec, tasks]
created: "2026-05-13"
---

# Tasks - ANSIBLE-021-tmux

> TDD order. One task = one focused commit.

## Setup

- [ ] Branch created from main: `feat/ANSIBLE-021-tmux`
- [ ] `proposal.md` reviewed; no open questions

## Implementation

- [ ] Add `tmux` to `base_system` role packages list (one-line YAML change)
- [ ] Run `make provision NODE=ace1 ENV=homelab` (or equivalent) — verify idempotent, `tmux` installed
- [ ] Run on remaining hosts: ace2, rpi4, rpi3, beelink, vps, aws1
- [ ] Execute smoke loop: `for h in ace1 ace2 rpi4 rpi3 beelink vps aws1; do ssh "$h" tmux -V; done` — capture output

## Closing

- [ ] All hosts return `tmux 3.x` (or similar)
- [ ] Jetson explicitly excluded — confirm
- [ ] Diff is a single-line role change + zero changes elsewhere (no scope creep)
- [ ] `verification.md` filled in (or marked deferred — low risk)
- [ ] PR opened, ANSIBLE-021 ticked in `kubelab/11-tasks.md` with PR link
