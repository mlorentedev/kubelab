---
tags: [spec, verification, templates]
created: "2026-06-29"
---

# Verification - ANSIBLE-028-dev-node

## Evidence

Criteria map to `features.json` (f1–f8). Static criteria are proven now; runtime
criteria are `pending` until the role is provision-applied (needs a Linux controller).

- [x] f1 (role exists + wired) — files under `infra/ansible/roles/dev_node/`, wired in `provision-ace2.yml`
- [x] f7 (D6 split tracked) — ANSIBLE-030 (#858)
- [ ] f2, f3, f4, f5, f6, f8 — verified on provision-apply (`make provision NODE=ace2`)

## Test status

- Ansible role, not a unit suite — verification is `features.json` commands run
  against the provisioned node.
- Static: role structure + playbook wiring + spec artifacts present.
- **Provisioning NOT yet run**: the dev workstation is Windows, and Ansible's control
  node must be Linux/macOS (`ansible-playbook` is unavailable here). Runtime criteria
  are verified from a Linux controller.
- No regressions: additive only — new role + one `roles:` entry; no existing role,
  var, or the Ollama/glances stack is touched.

## Decisions made during implementation

- **D6 housekeeping timers split to ANSIBLE-030 (#858)** to keep PR-1a within the
  atomic-PR cap, exactly as the proposal foresaw. `handlers/main.yml` ships empty
  with a note that the timer handlers land there.
- **tmux-resurrect via a vendored, pinned `git` clone** (not TPM) — idempotent and
  offline-tolerant; a single marked `run-shell` line is added to `.tmux.conf` (only
  the resurrect wiring; general tmux prefs stay a dotfiles concern per the proposal).
- **mise: install script + pinned toolchains in the global config**; activation added
  to `.bashrc`/`.zshrc` via marked blocks. **Open for provision validation:** node/go/
  python resolving in a *non-login* shell (the proposal's flagged risk) — confirm the
  shims path is visible to Ansible `command` tasks and agent processes, not just zsh.
- **`dev_node_user` from `networking.ssh_users.homelab`** (SSOT), not a hardcoded name.
- **dotfiles bootstrap runs `setup-linux.sh`** with `changed_when` tied to the repo
  clone state. **Open for provision validation:** setup-linux.sh idempotency + that it
  pulls no secret material (secrets are PR-1c's concern).

## Promotion candidates

- [ ] Lesson for `docs/lessons.md`? Maybe — "Ansible control node can't be Windows;
  provisioning needs a Linux controller" (decide after first provision run).
- [ ] ADR-worthy? No — ADR-058 already covers the decision.
- [ ] New pattern for `00_meta/patterns/`? No.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-028-dev-node/` -> `specs/archive/ANSIBLE-028-dev-node/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
