---
tags: [spec, tasks, templates]
created: "2026-06-29"
---

# Tasks - ANSIBLE-028-dev-node

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.

## Setup

- [x] Branch created: `feat/ANSIBLE-028-dev-node` ✓ 2026-06-29 (rebased onto master 2026-07-09)
- [x] `proposal.md` complete; acceptance criteria testable ✓ 2026-06-29
- [x] Open questions resolved (see verification.md "Decisions") ✓ 2026-07-09

## Implementation

> Ansible role, not a test-first unit — "tests" are the `features.json` verification
> commands run against the provisioned node. Provisioning needs a Linux Ansible
> controller (this repo's dev workstation is Windows); runtime criteria are verified
> when the role is applied.

- [x] `dev_node/defaults/main.yml` — user, mise, tmux-resurrect, dotfiles, workspace, apt vars ✓ 2026-07-09
- [x] `dev_node/tasks/main.yml` — neovim + gh (apt repo); mise + pinned toolchains; tmux-resurrect vendored clone + wiring; dotfiles clone + bootstrap; workspace skeleton; dev-session.sh ✓ 2026-07-09
- [x] `dev_node/templates/{mise-config.toml,dev-session.sh}.j2` ✓ 2026-07-09
- [x] `dev_node/handlers/main.yml` (empty — D6 handlers land in ANSIBLE-030) ✓ 2026-07-09
- [x] Wired into `provision-ace2.yml` (`dev_node_user` from `networking.ssh_users.homelab` SSOT) ✓ 2026-07-09
- [x] D6 housekeeping timers split to follow-up ANSIBLE-030 (#858) ✓ 2026-07-09
- [ ] **Provision-verify** on ace2 (needs Linux controller): `make provision NODE=ace2 ENV=staging --tags dev_node` — idempotency, Ollama coexistence, tools present, mise resolves, dev-session launches
- [ ] Iterate on provisioning output (mise non-login activation, dotfiles idempotency — flagged in proposal)

## Closing

- [x] Every acceptance criterion has a `features.json` entry with an executable verification command ✓
- [x] YAML lint passes (pre-commit yamllint) — verify at commit
- [x] No unrelated changes in the diff (no scope creep) ✓
- [x] `verification.md` filled in ✓
- [ ] PR opened (draft) referencing this spec folder — runtime `features.json` still `pending`

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/ANSIBLE-028-dev-node/features.json`):

```json
[
  {
    "id": "ANSIBLE-028-dev-node-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
