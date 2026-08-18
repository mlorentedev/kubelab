---
id: lesson-295-a-config-file-with-two-writers-can-never-conv
type: lesson
status: active
created: "2026-08-07"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# A config file with two writers can never converge — idempotence is a property of the system, not of the task (ANSIBLE-028)

**Context:** ANSIBLE-028 (#816), the `dev_node` role that provisions ace2 as a self-hosted CDE. The role wired mise activation and tmux-resurrect by injecting marked blocks into `~/.bashrc`, `~/.zshrc` and `~/.tmux.conf`. It also clones the dotfiles repo and runs its `setup-linux.sh` bootstrap.

**Problem:** Two consecutive provision passes reported `changed=2`, forever. Not flaky — *stable*, at exactly two. The dotfiles bootstrap redeploys those three rc files **wholesale on every run**, erasing whatever the role had written; the role then rewrote them on the next pass, and the cycle repeated. There is no ordering of those two tasks that converges: whoever runs last wins and the other one redoes its work next time.

The trap is that an earlier, *different* bug presented identically from outside. Initially the role wrote its block **before** the bootstrap, so the block vanished silently and the task still reported `changed`. Reordering fixed that — the block stopped disappearing — and the `changed=2` remained, which made it look like the same bug was only half-fixed. It was not: the first was a loss-of-write, the second was contention. Ordering cured one and could never cure the other.

**Solution:** Give every file exactly one owner. Ansible owns `/etc/profile.d/mise.sh` and the gitignored `*.local` seams (`~/.bashrc.local`, `~/.zshrc.local`, `~/.tmux.conf.local`); the dotfiles bootstrap owns the tracked rc files it deploys. The bash/zsh seams already existed upstream — gitignored, sourced last, never redeployed. tmux had none, so it was added upstream (`mlorentedev/dotfiles#788`). Second pass then reported `changed=0`, and stayed there even across a subsequent upstream dotfiles change (one changed pass to absorb it, then zero).

**Rule:** An Ansible task (or any provisioning step) that reports `changed` on **every** run is almost always contending for a file with another writer — look for the second writer before you touch the task's logic. The fix is ownership, not ordering. Corollary, and the more expensive half: **one green pass proves nothing about idempotence — the second pass is the test**, and the criterion must read the *task list*, not just the aggregate `changed=` count, because a task whose `changed_when` is derived from something else (a git clone's state, a marker file) can mask a non-converging step inside an otherwise clean total.

**Tags:** `#ansible` `#idempotence` `#dotfiles` `#config-ownership` `#provisioning` `#ansible-028` `#gotcha`
