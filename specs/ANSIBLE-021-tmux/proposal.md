---
id: "ANSIBLE-021-tmux"
type: spec
status: draft
created: "2026-05-13"
tags: [spec, proposal, ansible, base-system]
template_version: "1.0"
---

# ANSIBLE-021: Install tmux via base_system role

## Why

Dotfiles ship a `sshmux` helper (`.zsh/functions.zsh`) that uses `tmux` for SSH session persistence across drops. Currently `tmux` is not installed on most provisioned nodes — the helper silently falls back to plain SSH, defeating the purpose. Adding `tmux` to `base_system` makes the helper work uniformly on all interactive-session hosts.

Captured 2026-05-11 during dotfiles tmux integration.

## What

Add `tmux` to the `base_system` Ansible role's package list. Re-run `base_system` against the inventory targets it already covers:

- Homelab: ace1, ace2, rpi4, rpi3, beelink
- Cloud: vps, aws1

Jetson is deliberately excluded — Ubuntu 18.04, raw-only via ANSIBLE-014, not an interactive-session target.

## Out of scope

- Configuring `tmux.conf` defaults (dotfiles concern).
- Plugin managers (TPM).
- `sshmux` improvements (dotfiles).

## Risks / open questions

- Idempotency: apt module handles "already installed" gracefully. No risk.
- Side effects: `tmux` is ~1 MB, no service, no port. Zero blast radius.
- Verification load: re-running `base_system` against 7 hosts via existing `make provision` flow.

No open questions.

## Acceptance criteria

- [ ] `base_system` role defaults list includes `tmux` (single line change).
- [ ] Provisioning is idempotent (no failures; only "changed" on first run per host).
- [ ] Smoke succeeds on every covered host: `for h in ace1 ace2 rpi4 rpi3 beelink vps aws1; do ssh "$h" tmux -V; done`.
- [ ] Jetson NOT touched (verify smoke returns "command not found" for jetson or inventory inspection shows exclusion).

## References

- Issue: [#814](https://github.com/mlorentedev/kubelab/issues/814) (bitácora; tasks live in GitHub per ADR-018)
- Dotfiles: `~/Projects/dotfiles/.zsh/functions.zsh` — `sshmux` function
- Role: `infra/ansible/roles/base_system/`
