---
tags: [spec, verification, templates]
created: "2026-06-29"
---

# Verification - ANSIBLE-028-dev-node

## Evidence

Criteria map to `features.json` (f1–f8). All runtime criteria have now been exercised
against a real ace2 from a Linux controller (2026-08-06); the last open criterion (f4)
was closed by a scope decision on 2026-08-07.

- [x] f1 (role exists + wired) — files under `infra/ansible/roles/dev_node/`, wired in `provision-ace2.yml`
- [x] f2 (idempotent + coexists with Ollama) — pass 1 `changed=4`, pass 2 `changed=0`, exit 0 both; re-verified 2026-08-07 with the corrected command across a dotfiles update (`changed=2` then `changed=0`)
- [x] f3 (nvim, gh, tmux-resurrect, dotfiles present) — criterion command PASS; resurrect confirmed *loading* 2026-08-07
- [x] f4 (toolchain resolves in login + interactive shells) — both classes PASS; see "Scope of f4"
- [x] f5 (`dev-session.sh` launches named sessions) — 4 detached sessions, idempotent re-invoke
- [x] f6 (workspace skeleton + per-agent dirs) — criterion command PASS
- [x] f7 (D6 split tracked) — ANSIBLE-030 (#858)
- [x] f8 (Ollama still up) — container up throughout, 11434 listening

### Scope of f4 — decided 2026-08-07

f4 originally said "a fresh non-login shell", which conflates two shell classes that
behave differently. The criterion now reads **login + interactive**, and both PASS —
re-run as rewritten against a live ace2 on 2026-08-07, `rc=0` both halves, node
v24.19.0 / go1.26.5 / Python 3.12.13 in each. `/etc/profile.d/mise.sh` covers login,
the `.bashrc.local`/`.zshrc.local` seam covers interactive, and both put the same mise
shims on PATH.

**Non-interactive (`ssh host 'cmd'`) is explicitly out of scope.** That shell class
reads neither `/etc/profile.d` nor `~/.bashrc` — Ubuntu's stock `.bashrc` returns at
`[[ $- != *i* ]]` — so no change inside this role can reach it. This is a property of
the Unix shell startup model, not a defect in the role.

Accepted because every consumer named in ADR-058 D1 is already covered:

| Consumer | Shell class | Covered by |
| --- | --- | --- |
| Agents launched by `dev-session.sh` | interactive (inside tmux) | `.bashrc.local` seam |
| Operator SSH into the box | login | `/etc/profile.d/mise.sh` |
| This role's own toolchain task | none — absolute path | `~/.local/bin/mise install` |

Rejected, and why:

- **(b) `/etc/environment`** — would cover the non-interactive case, but the PATH there
  is static and system-wide, losing the `id -un` guard in `mise-profile.sh.j2`. Root
  and every other account would inherit `dev_node_user`'s toolchain.
- **(c) explicit shims path in each task** — works, but is a permanent discipline cost:
  every future task must remember the variable. No task needs it today.

**Consequence to know:** a future Ansible task, cron job, or CI step that shells into
ace2 non-interactively and calls a bare `node`/`go`/`python` will get the system
binary, not the pinned one. Such a caller must invoke via the absolute shims path.

### tmux-resurrect closed the loop — 2026-08-07

`mlorentedev/dotfiles#788` (the `~/.tmux.conf.local` seam) merged 2026-08-07. A
re-provision pulled it, and resurrect went from *installed* to *loading*: `~/.tmux.conf`
now carries the `if-shell` source line, and on an isolated socket the plugin binds
`prefix C-s` -> `save.sh` and `prefix C-r` -> `restore.sh`.

That run also re-verified f2 under the harder condition — convergence *across* an
upstream dotfiles change: `changed=2` (clone + bootstrap) then `changed=0`. This is the
single-owner split paying off: an upstream change costs exactly one changed pass, not a
permanent delta.

**Still unverified:** actual session restore across a reboot. The proposal's f5 criterion
said "tmux-resurrect restores them across a reboot"; `features.json` f5 only verifies
that `dev-session.sh` launches the sessions. The bindings and options are now proven
present, but a real power-cycle test has never run. Tracked as **ANSIBLE-032
([#884](https://github.com/mlorentedev/kubelab/issues/884))** rather than claimed — the
boundary is deliberate, not an oversight.

### Criterion commands must be executable as written

f2's command read `make provision NODE=ace2 ENV=staging --tags dev_node`. `make` rejects
that outright (`make: unrecognized option '--tags'`); the Makefile's interface is
`TAGS=dev_node`. The criterion had been *satisfied* in practice by running the correct
form by hand, but the recorded command could never reproduce it. Corrected 2026-08-07
and re-run as written.

Same failure mode as the f4 rewrite: a criterion whose text drifts from what was
actually executed is not a criterion, it is a note. Every command in `features.json` is
now confirmed runnable verbatim.

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
  The residual non-interactive gap is an accepted scope boundary (see "Scope of f4"),
  not a mise defect.
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
- [x] **Lesson for `docs/lessons.md` — YES, promote at archive.** Working title: "A
  config file with two writers can never converge — idempotence is a property of the
  system, not of the task." Body: the role injected blocks into `~/.bashrc`,
  `~/.zshrc`, `~/.tmux.conf` while the dotfiles bootstrap redeployed those same files
  wholesale every run, so two consecutive passes reported `changed=2` forever.
  Reordering only fixed the *loss* of the block (a different bug that presents
  identically from outside); the churn needed single ownership — the provisioner
  writes `/etc` and the gitignored `*.local` seams, the dotfiles bootstrap owns the
  tracked rc files. Diagnostic rule: an Ansible task that reports `changed` on every
  run is almost always contending for a file with another writer, not misconfigured.
  Corollary: one green pass proves nothing about idempotence — the second pass is the
  test, and the criterion must read the *task list*, not just the aggregate count.
- [x] **Cross-project? YES — candidate for `00_meta/patterns/`.** The rule generalizes
  past Ansible to any provisioner-plus-dotfiles pairing (chezmoi, Nix home-manager,
  Puppet). Suggest folding into an existing pattern rather than a new file — closest
  homes are `pattern-setup-script-idempotence` and `pattern-contract-defaults-per-machine-override`.
  Decide at archive per [[feedback_no_doc_proliferation]].
- [ ] ADR-worthy? No — ADR-058 already covers the decision.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-028-dev-node/` -> `specs/archive/ANSIBLE-028-dev-node/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
