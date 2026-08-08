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

ace2 gains a **machine identity of its own**: a single fine-grained GitHub PAT, provisioned by the `dev_node` role, that authenticates both `gh` and `git` over HTTPS.

Observable after this PR, none of which is possible today:

1. `gh auth status` on ace2 reports an authenticated account, and `gh pr create` works from a non-interactive shell inside a tmux session.
2. An agent working in `~/workspaces/<agent>/` clones a **private** kubelab-org repository, commits, pushes a branch and opens a PR — with no human at the keyboard and no agent forwarding.
3. That identity is **not the operator's**. It reaches only the repositories named in the token's scope, carries only `contents` + `pull-requests` write, and **stops working on a date GitHub enforces** rather than a date someone remembers.

The mechanism is one credential, not two: `gh auth login --with-token` followed by `gh auth setup-git` makes the same PAT serve git pushes over HTTPS, so there is one secret to rotate and one to revoke. No SSH private key is placed on the node.

### The token contract

**Name:** `ace2-dev-node-2026-08`, following `<host>-<purpose>-<YYYY-MM>`.

The host leads because the question a token name has to answer is asked during an incident: *which machine loses access if I revoke this?* The purpose (not the project) follows, per OPS-007's per-purpose convention. The issue month is **not** redundant with the expiry GitHub already displays: a 90-day rotation means two live tokens during the overlap, and you need to tell the new one from the old at a glance. Next is `ace2-dev-node-2026-11`. Deliberately no ticket id — the token rotates, the ticket does not; that traceability lives here.

**SOPS path:** `apps.services.automation.dev_node.github_token` in **`common.enc.yaml`**, mirroring the existing `apps.services.automation.github_runner.token`.

Common, not per-environment, because this token is **machine identity, not environment configuration**: it authenticates ace2 to GitHub, and GitHub is not an environment. The node does not deploy with it — it clones and pushes. Confirmed reachable: `provision-ace2.yml` decrypts `common.enc.yaml` and `<env>.enc.yaml` controller-side and merges them (env overriding common), so a role var sourced from common resolves normally.

**Permissions — granted:**

| Permission | Level | Why |
| --- | --- | --- |
| Contents | Read and write | Clone private, and push. Without write there is no `git push` |
| Pull requests | Read and write | `gh pr create` |
| Metadata | Read | Mandatory — GitHub forces it alongside any repository permission |
| Checks | Read | So the agent can see whether its own PR went green |
| Commit statuses | Read | Same purpose; some checks report here rather than through the Checks API |

The two read permissions close the loop: an agent that opens a PR and cannot observe whether CI passed is only half-useful. They widen no blast radius.

**Permissions — refused, with the consequence stated up front:**

- **`Workflows: write` — refused.** Consequence to know before it surprises someone: **any push touching `.github/workflows/` will be rejected by GitHub.** That is the intended behaviour. This repo's CI runs on a self-hosted runner with access to secrets, so a token that can rewrite a workflow is a token that can execute arbitrary code with those secrets. It is the single largest privilege jump available in this list and it arrives disguised as "I just need to edit a YAML". Workflow changes go through a human.
- **`Issues: write` — refused.** Agents have no need to file tickets yet; add it the day that changes rather than pre-granting.
- **`Actions: write` — refused.** No part of the flow triggers or cancels workflow runs.

General rule this list follows: **write only where the flow demands it, read where the agent only needs to observe.**

## Out of scope

- **Implementing Bitwarden-over-API** (`dotfiles#585`). This spec is the interim that exists *because* that is missing, and its exit trigger.
- **The autonomous-agent jail** — ADR-058 D3 peldaño-2 (policy jail, `NOPASSWD` reversal for the agent user, human-approval channel). Trigger-gated, and mixing it in would make this unreviewable.
- **Any prod credential**: no prod SOPS key, no prod kubeconfig, no prod-scoped token. Non-negotiable per D3 and not softened by anything here.
- **A GitHub App** — documented in Risks as the graduation path, deliberately not built now.
- **SSH deploy keys** — evaluated and rejected below; no per-repo SSH key material ships.

## Risks / open questions

- **The at-rest credential is the whole deviation.** ADR-058 D3 says secrets are "fetched on unlock, not stored at rest". A PAT in SOPS rendered onto the node is at rest. Accepted deliberately and time-boxed by the token's own expiry — **this is why expiry is a hard requirement, not a nicety**: it is the only part of the time-box that does not depend on anyone remembering. **Resolved 2026-08-07: 90 days.** The honest middle — it forces the interim to be revisited four times a year without making rotation a chore, and with `dotfiles#585` parked since 2026-07-02 the recurring reminder is the point. 30d was rejected because ace2 is on-demand and could well be powered off on expiry day; 1y was rejected as indistinguishable from permanent.
- **A token on a build host is reachable by anything that runs there.** A malicious transitive dependency in an `npm install`, or an agent executing its own generated code, runs as the same user and can read it. This is the argument for the narrowest possible repo list and for `contents`+`pull-requests` only — no `admin`, no `workflow`, no org scopes. The dev node is a wider attack surface than a laptop, and the token must be sized for that, not for convenience.
- **Rejected: SSH key on the operator's GitHub account.** Cannot be scoped — GitHub account keys are all-or-nothing, so ace2 would reach every private repo the operator reaches, in every org, for as long as the key lives. Revocability per node gives traceability, not isolation. This was the agent's initial recommendation and it was wrong; recorded so the reasoning is not re-litigated.
- **Rejected: SSH deploy keys.** Genuinely per-repo, but GitHub forbids reusing one key across repositories (N repos = N keys), and `gh` cannot authenticate with them at all — so it solves half the requirement and scales badly against a dev node that touches several repos.
- **Graduation path: GitHub App.** Short-lived (~1h) installation tokens, scoped to the installation. Note the nuance that decides *when* it is worth it: minting tokens needs **no hosting** (sign a JWT locally, exchange it for a token — webhooks are what require a public endpoint, and we want none). But if the App private key lives on ace2, it is a non-expiring key that mints tokens forever — strictly worse than a PAT with an expiry. The App only pays off when the key lives **off** the node, on the always-on tier (VPS or aws1), which makes it a service to build and operate. **Open question for a later ADR, not this spec** (confirmed 2026-08-07): the App and D3's Bitwarden-over-API solve the same problem — no long-lived secret at rest — and for *machine* identity the App is arguably the better fit than a human-oriented secret manager. Worth reconciling before #585 lands and settles it by default.

  Placement, so that ADR does not start from zero. The obvious candidate is **aws1**: it is the always-on management plane (ADR-023 hub-and-spoke), and issuing credentials is a management-plane function. The objection is that Argo CD lives there **with prod deploy rights** — colocating the App's private key puts two credential authorities on one host, so compromising aws1 would yield both "deploy anything to prod" and "mint a GitHub token for any repo". That sits badly with D3's own principle that a compromised dev-node cannot reach prod: the issuer would be *adjacent* to prod. The VPS has the same shape (prod K3s runs there), so **every always-on option colocates with something sensitive** — which is exactly why this is an architecture decision and not a slot to fill. Note also aws1 is a t4g.small with roughly 1GB headroom and a prior OOM history, so "small service, plenty of room" is not automatic. Worth stating plainly: Argo CD and a token minter share the always-on tier, they do not share a function — Argo *reads* git to deploy, the minter would issue *write* credentials for development. Opposite directions, different consumers.
- **Assumption this spec depends on: ace2 holds no age key.** The token is safe on the node only because the *controller* decrypts SOPS and renders the value — ace2 itself cannot decrypt anything. Verified 2026-08-07: no `~/.config/sops/age/keys.txt`, no `~/.age/key.txt`, no `/etc/sops/age.key`, `sops` not installed, no `~/.kube`. This matters because ADR-058 D3's stated control — a *staging-scoped* SOPS key — **does not exist**: `common`, `staging` and `prod` are all encrypted to the same two age recipients, so any key decrypts prod. D3's property currently holds **by absence, not by design**. The day D2's dev loop puts an age key on ace2, that breaks. Tracked as **SEC-SOPS-001 ([#889](https://github.com/mlorentedev/kubelab/issues/889))**, deliberately not fixed here; AC5 asserts the absence so this spec fails loudly if the assumption ever silently changes.
- **Dependency risk, stated plainly:** `dotfiles#585` has not moved since 2026-07-02. An interim whose exit depends on a parked ticket is how "temporary" becomes permanent. The token's expiry is the mitigation.

## Acceptance criteria

- [ ] AC1: `ssh ace2 'gh auth status'` reports an authenticated account and exits 0 — i.e. `gh` works non-interactively, not only in a login shell.
- [ ] AC2: From a tmux session on ace2, a private repository clones, accepts a commit, pushes a branch and opens a PR via `gh pr create`, with no agent forwarding and no human interaction.
- [ ] AC3: The token is fine-grained with a **90-day** expiry, limited to an enumerated repository list, and grants only `contents` + `pull-requests` write. Verified by inspecting the token's own metadata (`gh api /rate_limit -i` surfaces the scopes header; expiry and repo list from the token's settings page or `gh api /user` under the token), not by intent.
- [ ] AC4: The credential is delivered by the `dev_node` role from SOPS — `make provision NODE=ace2 ENV=staging TAGS=dev_node` provisions it reproducibly, and a second pass reports `changed=0`.
- [ ] AC5: No prod credential is reachable from ace2. Runnable as written, not intent: `ssh ace2 '! test -e ~/.config/sops/age/keys.txt && ! test -e ~/.age/key.txt && ! test -e /etc/sops/age.key && ! command -v sops && ! ls ~/.kube/*prod* 2>/dev/null'` exits 0. The age-key half is **load-bearing, not belt-and-braces**: per SEC-SOPS-001 (#889) any age key on this node decrypts prod, so its absence is the actual control. (Final path list to be pinned in `tasks.md` against the real prod artefact names.)
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
