---
id: "ANSIBLE-021-tmux"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-05-13"
issue: "kubelab#420"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, ansible, base-system]
template_version: "1.0"
---

# ANSIBLE-021: Install tmux via base_system role

## Why

Dotfiles ship a `sshmux` helper (`.zsh/functions.zsh`) that uses `tmux` for SSH session persistence across drops. Currently `tmux` is not installed on most provisioned nodes — the helper silently falls back to plain SSH, defeating the purpose. Adding `tmux` to `base_system` makes the helper work uniformly on all interactive-session hosts.

Captured 2026-05-11 during dotfiles tmux integration.

## What

Add `tmux` to the `base_system` Ansible role's package list. Under the per-node `make provision NODE=x` flow, `base_system` runs on **5 nodes**:

- Homelab: ace1, ace2, beelink, rpi4
- Cloud: aws1

**vps and rpi3 are NOT covered by this change**: their bespoke playbooks (`provision-vps.yml`, `provision-rpi3.yml`) deliberately omit `base_system`. They receive tmux as part of the minimal-baseline fix in **ANSIBLE-029 (#817)** — not bolted onto the prod K3s playbook here.

> **Both halves of that paragraph have since stopped being true, and neither changed for the reason it predicted (measured 2026-08-18, before archiving).**
> **rpi3 now runs `base_system`** — `provision-rpi3.yml:105` — and therefore gets tmux (3.5a, measured). It did not arrive via #817, which is still OPEN: it came in with `3c9629b`, *fix(ansible): give rpi3 a host firewall via base_system (#1059)*, on 2026-08-13. A scope boundary this spec drew moved because an unrelated fix adopted the role for a different reason.
> **The VPS has tmux 3.4 and is covered by nothing.** `provision-vps.yml` still omits `base_system` — deliberately, and its inline comment now explains why in more detail than this spec did — and neither it nor any other playbook installs tmux. So the package is present and unmanaged: a rebuild from scratch would not reinstall it. That is #817's subject, not this spec's, and it is recorded there.

Jetson is deliberately excluded — Ubuntu 18.04, raw-only via ANSIBLE-014, not an interactive-session target (its `provision-jetson.yml` also omits `base_system`).

## Out of scope

- Configuring `tmux.conf` defaults (dotfiles concern).
- Plugin managers (TPM).
- `sshmux` improvements (dotfiles).

## Risks / open questions

- Idempotency: apt module handles "already installed" gracefully. No risk.
- Side effects: `tmux` is ~1 MB, no service, no port. Zero blast radius.
- Verification load: re-running `base_system` against 5 hosts via existing `make provision` flow.

No open questions.

## Acceptance criteria

- [ ] `base_system` role defaults list includes `tmux` (single line change).
- [ ] Provisioning is idempotent (no failures; only "changed" on first run per host).
- [ ] Smoke succeeds on every covered host: `for h in ace1 ace2 aws1 beelink rpi4; do ssh "$h" tmux -V; done`.
- [ ] Jetson NOT touched (verify smoke returns "command not found" for jetson or inventory inspection shows exclusion).

## References

- Issue: [#420](https://github.com/mlorentedev/kubelab/issues/420) (canonical; bitácora per ADR-018)
- Systemic baseline-coverage gap: [#817](https://github.com/mlorentedev/kubelab/issues/817) (ANSIBLE-029) — vps/rpi3 tmux lands there
- Host context: ADR-058 (ace2 dev-node)
- Dotfiles: `~/Projects/dotfiles/.zsh/functions.zsh` — `sshmux` function
- Role: `infra/ansible/roles/base_system/`
