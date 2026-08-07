---
tags: [spec, verification, templates]
created: "2026-06-29"
---

# Verification - ANSIBLE-028-dev-node

## Evidence

Criteria map to `features.json` (f1–f8). All runtime criteria have now been exercised
against a real ace2 from a Linux controller (2026-08-06).

- [x] f1 (role exists + wired) — files under `infra/ansible/roles/dev_node/`, wired in `provision-ace2.yml`
- [x] f2 (idempotent + coexists with Ollama) — pass 1 `changed=4`, pass 2 `changed=0`, exit 0 both
- [x] f3 (nvim, gh, tmux-resurrect, dotfiles present) — criterion command PASS
- [x] f5 (`dev-session.sh` launches named sessions) — 4 detached sessions, idempotent re-invoke
- [x] f6 (workspace skeleton + per-agent dirs) — criterion command PASS
- [x] f7 (D6 split tracked) — ANSIBLE-030 (#858)
- [x] f8 (Ollama still up) — container up throughout, 11434 listening
- [ ] **f4 (toolchain resolves in a "fresh non-login shell") — the one open criterion.**
      Login and interactive shells PASS (shims via `/etc/profile.d` + the `.local`
      files). Non-interactive (`ssh host 'cmd'`) FAILS and is not fixable from this
      role: it reads neither `profile.d` nor `.bashrc`, whose Ubuntu stock copy
      returns at `[[ $- != *i* ]]`. **Needs a human wording decision** — see
      `features.json` f4 evidence. Options: (a) narrow the criterion to
      login+interactive (passes today), (b) add `/etc/environment` (static PATH,
      system-wide, loses the per-user guard), (c) keep it narrow and have Ansible
      tasks use the explicit shims path.

## Test status

- Ansible role, not a unit suite — verification is `features.json` commands run
  against the provisioned node.
- Static: role structure + playbook wiring + spec artifacts present.
- ~~**Provisioning NOT yet run**~~ — **resolved 2026-08-06.** The historical note was
  that the dev workstation was Windows, which cannot be an Ansible *control node* by
  design (the controller needs POSIX primitives — `os.fork()`, ptys, `ssh`). Runtime
  criteria have now been exercised from a Linux controller on the mesh
  (`msi`, 100.64.0.1, ansible-core 2.20.0) against a powered-on ace2. Note the
  bastion transport (TOOL-016 / #818) was **not** needed: from a mesh controller the
  default `mesh` transport reaches ace2 directly.

### First real provision run — four defects (2026-08-06)

Every one of these needed a real remote repo and a real target node. None was
reachable by lint, unit tests, or code review — which is the empirical
justification for having kept f2–f6/f8 `pending` instead of assuming them.

1. **`dev_node_dotfiles_version: "master"`** — that repo's default branch is `main`
   (`git ls-remote --symref … HEAD`). The kubelab branch convention leaked into a repo
   that does not share it. `git checkout master` failed outright.
2. **`setup-linux.sh` run from the wrong CWD** — it sources `./scripts/utils.sh`
   relative to the CWD and documents `Usage: ./setup-linux.sh`, so repo root is part
   of its contract. Ansible ran it from `$HOME`; it died in 0.002s. Added `chdir`.
3. **mise activation clobbered by the dotfiles bootstrap** — the activation block was
   written to `.bashrc`/`.zshrc` *before* the bootstrap, which deploys its own copies
   of both files. The managed block vanished silently (the task still reported
   `changed`). Ordering is now load-bearing and documented as such in `tasks/main.yml`.
4. **`become: true` was not enough for `/etc/profile.d`** — the enclosing `block:`
   sets `become_user: dev_node_user`, which a task-level `become: true` inherits.
   Needed an explicit `become_user: root`.

### Config ownership — the fix that made f2 converge (2026-08-06)

The first full run exposed a fifth, structural defect: two consecutive passes gave
`changed=2`, forever. The recurring tasks were the tmux-resurrect wiring and the mise
activation — both writing into `~/.bashrc`, `~/.zshrc`, `~/.tmux.conf`, which
`setup-linux.sh` **redeploys wholesale on every run**.

No task ordering can fix that. While two writers own one file, the last one wins and
the other re-does its work next pass; convergence is impossible by construction.
Reordering (defect 3) fixed the silent *loss* of the block, which looked like the same
bug from outside but was not.

Resolved by giving every file a single owner:

| File | Owner | Written by |
| --- | --- | --- |
| `~/.bashrc`, `~/.zshrc`, `~/.tmux.conf` | dotfiles | `setup-linux.sh` only |
| `~/.bashrc.local`, `~/.zshrc.local`, `~/.tmux.conf.local` | Ansible | this role only |
| `/etc/profile.d/mise.sh` | Ansible | this role only |

`~/.bashrc.local` / `~/.zshrc.local` already existed as the dotfiles-side seam
(IDEAS-001): gitignored, sourced last by the tracked rc files, never redeployed. tmux
had no equivalent, so the seam was added upstream (**mlorentedev/dotfiles#788**,
`if-shell`-guarded, no-op where the file is absent). Note #788 does not gate f2 — the
role converges regardless — but tmux-resurrect will not *load* on ace2 until it merges.

Also dropped `eval "$(mise activate …)"` in favour of shims on PATH, so the `.local`
files and `/etc/profile.d` use one mechanism instead of two for the same job.

### Cross-repo dependency — was BLOCKING f2 (resolved 2026-08-06)

`setup-linux.sh` aborts on any node whose user has **no crontab yet**: it runs
`(crontab -l 2>/dev/null; echo …) | crontab -` under `set -euo pipefail`, and
`crontab -l` exits 1 on an empty crontab, killing the subshell before the `echo` and
propagating via `pipefail`. Invisible on every machine that already had a crontab —
i.e. every machine the script had ever run on.

Fix: **mlorentedev/dotfiles#783**, merged 2026-08-06. The role clones from GitHub
`main`, so the fix reached ace2 on merge — not when the PR was opened. The first full
run to complete end-to-end came immediately after.

- No regressions: additive only — new role + one `roles:` entry; no existing role,
  var, or the Ollama/glances stack is touched. Confirmed at runtime: the Ollama
  container stayed up across every provision pass, 11434 listening throughout.

## Decisions made during implementation

- **D6 housekeeping timers split to ANSIBLE-030 (#858)** to keep PR-1a within the
  atomic-PR cap, exactly as the proposal foresaw. `handlers/main.yml` ships empty
  with a note that the timer handlers land there.
- **tmux-resurrect via a vendored, pinned `git` clone** (not TPM) — idempotent and
  offline-tolerant; a single marked `run-shell` line goes to **`.tmux.conf.local`**
  (revised 2026-08-06 from `.tmux.conf`, which dotfiles owns — see the ownership
  section above; general tmux prefs stay a dotfiles concern per the proposal).
- **mise: install script + pinned toolchains in the global config**; activation via
  **`/etc/profile.d/mise.sh` + `.bashrc.local`/`.zshrc.local`** (revised 2026-08-06
  from `.bashrc`/`.zshrc`). An explicit `file: state=directory` creates `~/.config/mise`
  before the config `template` — `template`/`copy` do not create the destination's
  parent dir, so the first run would fail on a fresh node without it.
  **Resolved at provision:** shims (not `mise activate`) are used precisely so the
  toolchain resolves outside interactive shells; verified for login and interactive.
  The residual non-interactive gap is f4's open wording question, not a mise defect.
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
