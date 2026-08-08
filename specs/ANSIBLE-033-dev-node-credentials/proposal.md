---
id: "ANSIBLE-033-dev-node-credentials"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-07"
issue: "kubelab#888"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-033: Dev node credentials — interim staging-scoped identity

> **Naming**: file lives at `<repo>/specs/ANSIBLE-033-dev-node-credentials/proposal.md`. `ANSIBLE-033-dev-node-credentials` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #888: ANSIBLE-033: dev node credentials — interim staging-scoped identity (PR-1c of ADR-058) -->

The dev node ships with a working toolchain and no identity. Verified on ace2 2026-08-07: node/go/python pinned and resolving, `nvim`/`gh`/`git`/`docker`/`tmux` present, agent workspaces created — but `gh auth status` reports not logged in and `~/.ssh` holds only a public key. You can edit, build and run; you cannot clone a private repo, push, or use `gh`. That gap is the whole distance between "there is a dev node" and "I work there", and it blocks the agent workflow D1 exists to enable.

## What

> `[AGENT-DRAFT — review before archive]` — drafted by the agent at the user's request; the user approves or edits before archive.

ace2 gains a **machine identity of its own**: a single fine-grained GitHub PAT, provisioned by the `dev_node` role, that authenticates both `gh` and `git` over HTTPS.

Observable after this PR, none of which is possible today:

1. `gh auth status` on ace2 reports an authenticated account, and `gh pr create` works from a non-interactive shell inside a tmux session.
2. An agent working in `~/workspaces/<agent>/` clones a **private** kubelab-org repository, commits, pushes a branch and opens a PR — with no human at the keyboard and no agent forwarding.
3. That identity is **not the operator's**. It reaches only the repositories named in the token's scope, carries only `contents` + `pull-requests` write, and **stops working on a date GitHub enforces** rather than a date someone remembers.

The mechanism is one credential, not two: `gh auth login --with-token` followed by `gh auth setup-git` makes the same PAT serve git pushes over HTTPS, so there is one secret to rotate and one to revoke. No SSH private key is placed on the node.

## Out of scope

> `[AGENT-DRAFT — review before archive]`

- **Implementing Bitwarden-over-API** (`dotfiles#585`). This spec is the interim that exists *because* that is missing, and its exit trigger.
- **The autonomous-agent jail** — ADR-058 D3 peldaño-2 (policy jail, `NOPASSWD` reversal for the agent user, human-approval channel). Trigger-gated, and mixing it in would make this unreviewable.
- **Any prod credential**: no prod SOPS key, no prod kubeconfig, no prod-scoped token. Non-negotiable per D3 and not softened by anything here.
- **A GitHub App** — documented in Risks as the graduation path, deliberately not built now.
- **SSH deploy keys** — evaluated and rejected below; no per-repo SSH key material ships.

## Risks / open questions

> `[AGENT-DRAFT — review before archive]`

- **The at-rest credential is the whole deviation.** ADR-058 D3 says secrets are "fetched on unlock, not stored at rest". A PAT in SOPS rendered onto the node is at rest. Accepted deliberately and time-boxed by the token's own expiry — **this is why expiry is a hard requirement, not a nicety**: it is the only part of the time-box that does not depend on anyone remembering. **MUST be resolved before implementation: what expiry?** A short one (30-90d) forces the migration honestly and costs a rotation each time; a long one (1y) is comfortable and lets the interim quietly become permanent.
- **A token on a build host is reachable by anything that runs there.** A malicious transitive dependency in an `npm install`, or an agent executing its own generated code, runs as the same user and can read it. This is the argument for the narrowest possible repo list and for `contents`+`pull-requests` only — no `admin`, no `workflow`, no org scopes. The dev node is a wider attack surface than a laptop, and the token must be sized for that, not for convenience.
- **Rejected: SSH key on the operator's GitHub account.** Cannot be scoped — GitHub account keys are all-or-nothing, so ace2 would reach every private repo the operator reaches, in every org, for as long as the key lives. Revocability per node gives traceability, not isolation. This was the agent's initial recommendation and it was wrong; recorded so the reasoning is not re-litigated.
- **Rejected: SSH deploy keys.** Genuinely per-repo, but GitHub forbids reusing one key across repositories (N repos = N keys), and `gh` cannot authenticate with them at all — so it solves half the requirement and scales badly against a dev node that touches several repos.
- **Graduation path: GitHub App.** Short-lived (~1h) installation tokens, scoped to the installation. Note the nuance that decides *when* it is worth it: minting tokens needs **no hosting** (sign a JWT locally, exchange it for a token — webhooks are what require a public endpoint, and we want none). But if the App private key lives on ace2, it is a non-expiring key that mints tokens forever — strictly worse than a PAT with an expiry. The App only pays off when the key lives **off** the node, on the always-on tier (VPS or aws1), which makes it a service to build and operate. **Open question for a later ADR, not this spec:** the App and D3's Bitwarden-over-API solve the same problem — no long-lived secret at rest — and for *machine* identity the App is arguably the better fit than a human-oriented secret manager. Worth reconciling before #585 lands and settles it by default.
- **Dependency risk, stated plainly:** `dotfiles#585` has not moved since 2026-07-02. An interim whose exit depends on a parked ticket is how "temporary" becomes permanent. The token's expiry is the mitigation.

## Acceptance criteria

- [ ] AC1: `ssh ace2 'gh auth status'` reports an authenticated account and exits 0 — i.e. `gh` works non-interactively, not only in a login shell.
- [ ] AC2: From a tmux session on ace2, a private repository clones, accepts a commit, pushes a branch and opens a PR via `gh pr create`, with no agent forwarding and no human interaction.
- [ ] AC3: The token is fine-grained with an explicit expiry, limited to an enumerated repository list, and grants only `contents` + `pull-requests` write. Verified by inspecting the token's own metadata, not by intent.
- [ ] AC4: The credential is delivered by the `dev_node` role from SOPS — `make provision NODE=ace2 ENV=staging TAGS=dev_node` provisions it reproducibly, and a second pass reports `changed=0`.
- [ ] AC5: No prod credential is reachable from ace2. Runnable as written, not intent: `ssh ace2 '! test -e ~/.config/sops/age/keys.txt && ! ls ~/.kube/*prod* 2>/dev/null && ! kubectl config get-contexts -o name 2>/dev/null | grep -q prod'` exits 0. (Final path list to be pinned in `tasks.md` against the real prod artefact names.)
- [ ] AC6: The token value never appears in a process argument, a log line, or a world-readable file on the node (SEC-SECRETS-001 discipline). The token lands in `gh`'s own credential store with `0600` on the containing directory — not a hand-rolled dotfile — so `gh` owns its lifecycle.
- [ ] AC7: Expiry day is not a mystery outage. A one-line rotation procedure lives in `docs/runbooks/` naming what breaks (agent pushes start failing with 401), who is notified, and the exact command to mint and re-provision the replacement.

<!-- Completeness pass (the fill's Q6), run against this draft:
     ADDED — rotation runbook (AC7): an expiry-as-timebox only works if expiry day
       is a scheduled event rather than a surprise outage.
     ADDED — where the token lands (AC6): AC6 constrained the token's exposure but
       nothing said where it lives; `gh`'s own store beats a hand-rolled file.
     SKIPPED — rate limiting: a single node's git traffic is nowhere near any limit.
     SKIPPED — audit logging of token use: GitHub's own audit log covers it; adding
       node-side logging would duplicate it and risk logging the token itself. -->


## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
