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
- **Provisioning NOT yet run**: the dev workstation is Windows. Ansible does not
  support Windows as a *control node* by design (the controller needs POSIX
  primitives — `os.fork()`, ptys, `ssh`/`sshpass` — and there is no native
  `ansible-playbook` for Windows; confirmed: absent from Git Bash). Windows can only
  be a *managed* node. The supported path is a Linux controller: a remote homelab box
  (Beelink, same LAN as ace2) or this box's WSL Ubuntu — but that WSL is currently
  bare (no ansible/sops/poetry/make/tailscale) and mesh reachability + the SOPS/age
  key inside WSL are unproven, so the low-friction controller is a provisioned Linux
  host, not WSL here. Runtime criteria are verified from that controller.
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
  to `.bashrc`/`.zshrc` via marked blocks. An explicit `file: state=directory` creates
  `~/.config/mise` before the config `template` — `template`/`copy` do not create the
  destination's parent dir, so the first run would fail on a fresh node without it.
  **Open for provision validation:** node/go/python resolving in a *non-login* shell
  (the proposal's flagged risk) — confirm the shims path is visible to Ansible
  `command` tasks and agent processes, not just zsh.
- **`dev_node_user` from `networking.ssh_users.homelab`** (SSOT), not a hardcoded name.
- **dotfiles bootstrap runs `setup-linux.sh`** with `changed_when` tied to the repo
  clone state (`_dotfiles.changed`). **Open for provision validation, two named
  checks:** (1) setup-linux.sh idempotency — the `changed_when` proxy reports `ok`
  whenever the clone is unchanged, so it can MASK a non-idempotent script and give a
  false-green on f2 (`changed=0`); the Linux run must diff node state across the two
  passes, not trust the aggregate `changed=0` alone. (2) that it pulls no secret
  material (secrets are PR-1c's concern). A robust fix (gate the run on
  `_dotfiles.changed` or a success marker) is deferred to the provision session where
  the script's real behaviour can be observed — noted here, not churned blind.

## Promotion candidates

- [x] **Lesson for `docs/lessons.md` (HARNESS-024) — YES, promote at archive.** Wording:
  "Ansible has no native Windows control node (needs POSIX: fork/pty/ssh). Provision
  from a Linux controller — a homelab box on ace2's LAN, or WSL, but WSL needs its own
  ansible/sops/tailscale toolchain + SOPS key + mesh transport first." Fact is proven
  now; graduates to `docs/lessons.md` at archive (post first provision run) per the
  spec flow, so the WSL-viability caveat can be confirmed empirically then.
- [ ] ADR-worthy? No — ADR-058 already covers the decision.
- [ ] New pattern for `00_meta/patterns/`? No.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-028-dev-node/` -> `specs/archive/ANSIBLE-028-dev-node/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
