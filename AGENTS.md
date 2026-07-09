# AGENTS.md

> **Single Source of Truth for AI coding agents in this repo** (Claude Code,
> Copilot, Cursor, Codex, OpenCode). Repo-specific context lives here; the
> universal behaviour rules are *referenced* under §Workflow Rules — not
> duplicated. Deep operational gotchas live in [`CLAUDE.md`](CLAUDE.md), which
> overlays only Claude-specific tooling notes on top of this file.

## What this is

**KubeLab** — a personal Internal Developer Platform (IDP). The **L0
infrastructure layer** (this repo) providing K3s, networking, observability,
auth, and data services for a portfolio of products (L1 `kubelab-*` platform
services, L2 apps, L3 tools live in their own repos). Scope here is L0 only —
streams A, B, C3, D, E, G in the vault roadmap.

## Architecture (pointers — full detail in CLAUDE.md)

- **Cluster:** K3s `v1.34.4+k3s1`, namespace `kubelab`, single all-in-one node
  `ace1` (staging). Prod K3s on the Hetzner VPS. Hub is Argo CD on AWS `t4g.small`.
- **Networking:** Headscale `v0.28.0` (Docker Compose on VPS, stays *outside* K3s
  per ADR-015) + Tailscale mesh; split DNS → RPi4 Pi-hole → CoreDNS → K3s.
- **Always-on vs on-demand** hardware split per ADR-028 — see CLAUDE.md topology.
- **SSOT for config:** `infra/config/values/*.yaml` (`common.yaml` + per-env
  overlays). Secrets in SOPS (`*.enc.yaml`). **Never** `.env` files, **never**
  hardcode IPs/CIDRs — they live under `networking.*` in `common.yaml`.
- **K8s packaging:** custom apps (api/web/errors) = Kustomize; third-party =
  official Helm charts. Overlays in `infra/k8s/overlays/{staging,prod}/`.

## Key paths

| Path | Purpose |
|------|---------|
| `infra/k8s/` | K8s manifests (base + overlays) |
| `infra/config/values/` | Environment config SSOT (dev/staging/prod) |
| `infra/ansible/` | Node provisioning (K3s server/agent, errors, DNS) |
| `infra/stacks/` | Docker Compose stacks (local dev) |
| `toolkit/` | Python CLI (`tk` / `toolkit`) — will become kubelab-cli |
| `edge/` | Traefik, DNS gateway; `edge/errors/` error-pages source |
| `apps/` | Application source (api) |
| `docs/` | Build/operate docs (ADRs, runbooks, troubleshooting, lessons) |

## Inner loop

- **Deploy to a cluster:** `make deploy-k8s ENV=staging` (Kustomize) then
  `make apply-secrets ENV=staging` (SOPS → K8s Secrets via the toolkit).
- **Tests:** `make test` (toolkit unit suite) / `make test-e2e ENV=staging`.
- **New worktree:** run `make worktree-init` once under `.worktrees/` (installs
  the per-worktree `.venv`). `make help` lists all targets.

## Conventions

- **Trunk-based:** `master` is the only permanent branch. Feature branches use
  `feature/|fix/|hotfix/|chore/|docs/` prefixes; all PRs **squash-merge** to
  `master`. No `develop`.
- **Atomic PRs** — one logical change per PR, ~300-line cap (tests, lockfiles,
  generated files excluded).
- PR body includes `Closes #N` for each issue it resolves (one per line).
- **English only** in git/GitHub artifacts (commits, branches, PR/issue text,
  code comments). **No AI attribution.** **No internal phase/milestone refs** in
  branch names or commit messages. **Auto-merge forbidden** in every repo.
- Conventional Commits. `release-please` cuts per-app semver tags; only `fix:`
  (patch) and `feat:` (minor) trigger a release — `chore:` does not.
- Pre-commit hooks are shared via `core.hooksPath` (set at `make setup`).

## Documentation & knowledge placement

Build/operate docs live in [`docs/`](docs/) (docs-as-code): ADRs in
[`docs/adr/`](docs/adr/), architecture in `docs/architecture/`, runbooks in
`docs/runbooks/`, troubleshooting in `docs/troubleshooting/`, and project lessons
in [`docs/lessons.md`](docs/lessons.md). Cross-project patterns and session memory
live in the maintainer's vault, **not here**. Task/backlog state lives in the
**bitácora** GitHub Project (issues), per ADR-018 — not in git history or the
vault. Lessons that mature into critical gotchas graduate to CLAUDE.md.

## Spec-Driven Development

This repo follows the **Spec-Driven Development per feature** pattern. Canonical
workflow at `$VAULT_PATH/00_meta/skills/spec/SKILL.md` (`$VAULT_PATH` resolved via
machine.json per ADR-025 — never hardcode a literal path). SDD applies by default
for PR-sized changes (~50–300 LOC, public contract, new dependency, or a multi-PR
sequence). Subcommands:

| Trigger phrase | Subcommand |
|---|---|
| "create a spec for X", "scaffold spec X", "start working on X" | `init <feature-id>` (gated on an open GitHub issue, ADR-018) |
| "bootstrap substrate for X" | `bootstrap <feature-id>` (optional 4-section contract) |
| "fill in proposal for X", "help me write the proposal" | `fill <feature-id>` (Socratic) |
| "archive spec X", "close spec X" | `archive <feature-id>` |

Per-feature specs live at `specs/<feature-id>/`; archived at
`specs/archive/<feature-id>/` (never deleted — audit trail). **Skip SDD for:**
typos, comment-only edits, mechanical refactors, bug fixes <20 lines with an
obvious cause, doc-only changes. When in doubt, ask.

## Workflow Rules (read before first tool call)

This repo opts in to the global behaviour rules in `$DOTFILES/AGENTS.md`
(resolved via machine.json per ADR-025; fallback
`~/Projects/Workspace/dotfiles/AGENTS.md`) — the canonical cross-agent SSOT:
**Standing Orders** (automate-don't-instruct, SSOT, knowledge hygiene, clean-as-
you-go, consult patterns, enterprise-grade, noted=recorded, bitácora status,
worktrees-outside-repo), **Decision Hierarchy**, **Model Selection**, **Security
HALT** rules, and **Operational Rules**. Read it once at session start and apply
it. The repo-specific notes above and in `CLAUDE.md` override only where they are
more specific.
