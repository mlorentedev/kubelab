---
id: "ANSIBLE-028-dev-node"
status: implementing # draft | implementing | verifying | archived
created: "2026-06-29"
issue: "mlorentedev/kubelab#816"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, ansible, dev-node, cde]
template_version: "1.0"
---

# ANSIBLE-028-dev-node

## Why

ace2 (Acemagic-2, 12GB x86) is provisioned as an Ollama compute node but is effectively idle — nothing in the platform consumes its local inference. Meanwhile there is no dedicated development tier: tooling and mesh access are inconsistent across workstations, and agents (Claude Code, Codex, pi) run on whichever box has the repo, causing environment drift. ADR-058 (D1) decides to repurpose ace2 into a **centralized self-hosted CDE** whose environment is defined as IaC — the Ansible `dev_node` role is the SSOT, so onboarding (a replacement disk, or a future collaborator) is reproducible by construction rather than a manual ritual. This spec is **PR-1a** of that milestone: the additive, low-risk `dev_node` role. It does not remove Ollama (PR-2) and does not add routing or secrets scoping (PR-1b/1c).

## What

A new `infra/ansible/roles/dev_node/` role, wired into `provision-ace2.yml`, so that `make provision NODE=ace2 ENV=staging` turns ace2 from a near-clean Ubuntu 24.04 into a reproducible developer workspace. After this PR, provisioning ace2 yields, idempotently:

- **tmux-resurrect** layered on the base `tmux` package (base `tmux` ships via ANSIBLE-021 / #420; this role does **not** re-declare the package).
- **neovim** (headless editing).
- **mise**-managed language toolchains — `node`, `go`, `python` pinned in a versioned `.mise.toml` (single reproducible source of truth for tool versions).
- **gh** CLI.
- **dotfiles** applied for the interactive user (`networking.ssh_users.homelab`, e.g. `manu`): the role clones the dotfiles repo and runs its `setup`/`dotf` bootstrap (a dev-node is a development machine, so the "never clone on deploy targets" rule does not apply).
- **workspace skeleton**: `~/Projects/*`, `~/workspaces/{claude,codex,pi}-agent/` (each its own clone, for filesystem isolation between concurrent agents), `~/bin/`.
- **`~/bin/dev-session.sh`**: a tmux session launcher that opens named sessions per agent + editor; `tmux-resurrect` persists them across reboot.
- **housekeeping** (ADR-058 D6), codified as `systemd` timers: docker/buildx prune (size-capped), git branch+worktree prune + periodic gc, language-cache prune, agent-workspace reset script, and a disk-usage threshold alert via the existing Glances + notify fabric (NOTIFY-001).

**ace2 keeps Ollama running alongside** — this PR is purely additive (12GB holds both; on-demand `keep_alive` does not consume when idle).

## Out of scope

- `*.dev.kubelab.live` port-to-subdomain OIDC routing → **PR-1b**.
- Bitwarden capability scoping (staging-only secrets at rest) → **PR-1c**.
- Ollama retirement + Ansible group reclassification (`compute_nodes`→`dev_nodes`) → **PR-2** (subtractive multi-SSOT sweep; reclassification is deferred there to avoid colliding with the still-running Ollama role).
- Agent orchestration / DAG coordination — v1 is tmux isolation only (per #809).
- GPU inference, persistent CI runner on ace2 (CI stays on Beelink).
- `tmux.conf` defaults and `sshmux` improvements (dotfiles concern).

## Risks / open questions

- **Atomic-PR size.** The role (tooling + dotfiles + workspace + dev-session + tmux-resurrect + D6 timers) may exceed the ~300 LOC cap. Mitigation: if the core role alone approaches the cap, split the D6 housekeeping timers into a follow-up (ANSIBLE-030) and ship core first. Decide during `tasks.md`.
- **mise activation in non-interactive contexts.** mise must resolve tool shims for (a) Ansible tasks that invoke node/go/python, (b) agent processes launched by `dev-session.sh`, and (c) plain SSH login shells. Pin the mise version; verify activation works in a non-login shell, not only in an interactive zsh.
- **Coexistence with `ace2_services` (Ollama).** `dev_node` must not stomp ace2's existing Docker config, firewall, or the Ollama service. Verify additive provisioning leaves Ollama healthy.
- **dotfiles idempotency + no secret material.** The dotfiles bootstrap must be safe to re-run and must not pull secrets onto the box (secrets are PR-1c's concern via BW scoping). Confirm the dotfiles `setup` is idempotent and secret-free.
- **tmux-resurrect install method** (TPM vs vendored git clone) — resolve in `tasks.md`; prefer the method that is idempotent and offline-tolerant.
- **Clean-OS assumption.** "Reproducible from clean OS" is the goal, but ace2 is not wiped for this PR (Ollama stays). Verify idempotency on the *current* ace2 state, and note clean-OS reproducibility as a claim to validate when ace2 is next reimaged.

## Acceptance criteria

- [ ] `infra/ansible/roles/dev_node/` exists (`defaults/`, `tasks/`, `templates/`, `handlers/`) and is wired into `provision-ace2.yml`.
- [ ] `make provision NODE=ace2 ENV=staging` is idempotent (only "changed" on first run per item) and coexists with the running Ollama service.
- [ ] After provisioning: `tmux-resurrect`, `neovim`, `gh`, and dotfiles are present for the interactive user.
- [ ] `mise` is installed; `.mise.toml` pins node/go/python; `mise list` shows them and `node|go|python --version` resolve in a fresh non-login shell.
- [ ] `~/bin/dev-session.sh` launches named tmux sessions; tmux-resurrect restores them across a reboot.
- [ ] Workspace skeleton exists; `~/workspaces/{claude,codex,pi}-agent/` are present and re-clonable.
- [ ] Housekeeping timers are installed + active **or** split to a tracked follow-up (ANSIBLE-030); disk-threshold alert wired through NOTIFY-001.
- [ ] Ollama still runs on ace2 (no removal in this PR).
- [ ] Role diff respects the atomic-PR cap (housekeeping split out if it would exceed it).

## References

- Bitácora: [#816](https://github.com/mlorentedev/kubelab/issues/816) (ANSIBLE-028, this spec) · umbrella [#809](https://github.com/mlorentedev/kubelab/issues/809)
- ADR: `docs/adr/adr-058-ace2-dev-node.md` (D1 CDE, D4 migration decoupling, D6 housekeeping)
- Base tmux: [#420](https://github.com/mlorentedev/kubelab/issues/420) (ANSIBLE-021) · baseline-coverage gap [#817](https://github.com/mlorentedev/kubelab/issues/817) (ANSIBLE-029)
- Notify fabric for the disk alert: NOTIFY-001 (`specs/NOTIFY-001/`)
- Dotfiles: the dotfiles repo `setup`/`dotf` bootstrap
- Amended later by PR-2: ADR-028 (topology), ADR-029 (intelligence layer)
