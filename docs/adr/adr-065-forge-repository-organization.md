---
id: "adr-065-forge-repository-organization"
type: adr
status: accepted
created: "2026-08-26"
tags: [architecture, gitea, repositories, identity, backup]
related:
  - adr-061-stateful-service-placement
  - adr-062-platform-identity-model
  - adr-049-edge-object-storage-placement-doctrine
  - adr-028-operational-topology
issue: mlorentedev/kubelab#1076
owner: manu
---

# ADR-065: Forge Repository Organization

## Status

Accepted — 2026-08-26. Tracks [#1076](https://github.com/mlorentedev/kubelab/issues/1076) (TOOL-035), sequenced by [#1077](https://github.com/mlorentedev/kubelab/issues/1077) (IDP-034).

Extends [ADR-061](adr-061-stateful-service-placement.md), which decides *what Gitea is for* (private repositories only, Argo CD keeps reconciling from GitHub) but not how repositories are arranged inside it. Extends [ADR-062](adr-062-platform-identity-model.md), whose identity tiers this maps onto rather than duplicating.

## Date

2026-08-26

## Context

Gitea has run on the Beelink since ADR-061 and holds nothing. #1076 records why: *"today 'migrate a repo' means a manual `git push` to a new remote created by hand in the web UI — untracked, unrepeatable, and invisible to review."* The forge is provisioned; its contents are not.

Two questions had to be answered before any reconciler could be written, and both were answered by the operator on 2026-08-26.

**Mirror or move.** #1077 gates repository population on the backup work *by risk*: populating Gitea with canonical content before a restore has been exercised makes the first repository the first thing with no recovery path. Mirrors of GitHub-canonical repositories avoid that, because GitHub remains the recovery path. **The answer is move** — Gitea becomes canonical — so the risk is real and the cheap path is closed.

**Which repositories.** Measured against the GitHub API: 40 private repositories, 466 MB. Almost none of them move.

| | repositories | size | decision |
|---|---|---|---|
| `fae-brain`, `resume` | 2 | 3.2 MB | move — pilots |
| `openkm-brain` | 1 | 0.3 MB | move, after the pilots |
| `knowledge` | 1 | 85 MB | stays on GitHub |
| `iris` (public) | 1 | 0.3 MB | stays on GitHub, stays public |
| archived | 36 | 377 MB | stay on GitHub |

The exclusions carry more reasoning than the inclusions:

- **`knowledge` is the vault** — the knowledge plane `AGENTS.md`, `CLAUDE.md` and the hive MCP tools resolve against, written by every session. Gitea runs on the Beelink, which is on-demand homelab ([ADR-028](adr-028-operational-topology.md)). A vault whose canonical remote is reachable only when the homelab is powered changes how the knowledge plane *works*, not merely where it is stored. It is also the one repository whose loss is unrecoverable from anywhere else.
- **The 36 archived repositories** are 81% of the bytes and close to 0% of the value in moving. Frozen since 2026-02-08: GitHub stores them for free, they consume no Beelink disk, they enter no backup. Content that cannot change cannot be lost between backups — their RPO is infinite.

The remaining question, and the subject of this ADR, is *where inside Gitea* the moved repositories live.

## Decision

### D1 — Repositories belong to organizations, never to a user account

The reason is measured rather than stylistic, and it is the finding AUTH-004 already paid for: **Gitea's CLI has no user `rename`**, and repository ownership is a foreign key to a user row. That is precisely why ADR-062 preserved `manu` instead of renaming it — renaming the admin after the first push turns a configuration change into a repository-ownership migration with a downtime window.

Hanging repositories off a person rebuilds that trap on the day the forge stops being empty. An organization decouples ownership from identity: repositories belong to the org, and people and machines reach them through teams.

This maps onto ADR-062's tiers without inventing a second model:

| ADR-062 tier | Gitea |
|---|---|
| `superadmin` (`manu`) | Owners team |
| `operator` | scoped team |
| `machine` (`hefesto`) | write team, **owns nothing** |

`hefesto` owning no repository is a property, not an omission. A bot that owns repositories is a bot whose retirement is a data migration; a bot with write access through a team is revoked by deleting one membership row.

### D2 — Organizations are split by provenance, not by topic

```
teledyne/    fae-brain   openkm-brain
personal/    resume
kubelab/     — reserved for future platform projects
```

Provenance means *who owns the content*, and choosing that axis gives the organization a second job for free: **the org is the backup and retention class.** When the offsite tier lands ([ADR-049](adr-049-edge-object-storage-placement-doctrine.md) D3, sequenced in #1090/#596), "what gets copied to R2" is answered by reading the namespace rather than by maintaining a list — and a third party's material never inherits a personal repository's retention policy by accident.

That last point is the reason this is a decision and not a preference. If the `teledyne` organization holds material owned by a third party, the offsite destination is a decision to take deliberately rather than one to inherit from wherever `restic` happens to be pointed.

A topic axis was considered and rejected: topics change, provenance does not, and topic tells you nothing about who may hold a copy.

### D3 — Every organization is declared, including empty ones

`kubelab` is created while holding nothing. An organization that exists because someone once made it in the UI is state with no consumer — the failure lesson-380 describes, live in this repository before. Declaring it in `common.yaml` and letting the reconciler create it makes it *declared* state instead: reconciled like everything else, and readable rather than remembered.

The corollary binds the reconciler: it reports organizations and repositories that exist and are **not** declared. Import by accident must not become policy by inertia.

### D4 — The pilot retains its GitHub copy until cutover, and that is not a mirror

#1077's risk gate is unchanged and still binds. What changes is *when* it binds. A pilot that leaves the GitHub copy in place during its validation window puts nothing in Gitea that has no recovery path, so the gate is tripped at **cutover** — when the GitHub copy stops being authoritative — not at pilot start.

This is deliberately distinguished from the mirror architecture rejected above: a permanent dual-canonical arrangement was rejected, while retaining the source until a cutover is proven is a rollback plan. The distinction is *duration and intent*, and conflating them would either block the pilot needlessly or smuggle the rejected architecture back in permanently.

The question the cutover must answer, and this ADR does not: **what must be true before the GitHub copy of a moved repository is retired?**

## Consequences

- **`hefesto`'s token must widen.** Measured in AUTH-004 AC5: with `write:repository,write:user` it creates only under its own namespace — `POST /user/repos` → `repos/hefesto/...`, and admin endpoints correctly return 403. Organization creation is `POST /orgs/{org}/repos` and needs org membership plus `write:organization`. That is a change to what #1437 mints in Ansible, not to the reconciler, and it is the one part of this work that cannot be written without the Beelink powered.
- **`common.yaml` gains an organization → repository declaration**, and the toolkit gains a reconciler for it (#1076). Idempotent by construction, per the standing IaC rule.
- **Team structure, webhooks and branch protection as code stay with [#503](https://github.com/mlorentedev/kubelab/issues/503)**, and none of them gate the pilot. Dependency automation for Gitea-hosted repositories is #1384.
- **Nothing here weakens ADR-061.** Everything Argo CD reconciles stays on GitHub; this ADR arranges private repositories inside the forge and does not widen what the forge is for.

## Alternatives considered

**Repositories under the `manu` user account.** Rejected — D1. It is the shape ADR-062 spent a whole identity model escaping, and it fails silently: nothing looks wrong until an identity has to change, at which point the fix is a migration rather than an edit.

**Repositories under `hefesto`, the bot.** Rejected. It is what the current token scopes make easiest, which is the argument against it: letting the credential's default shape decide the ownership model inverts the decision. It also makes the bot's retirement a data migration.

**One organization, split by topic.** Rejected — D2. It answers "what is this about" and the questions that actually recur are "who owns this" and "who may hold a copy".

**Create organizations lazily, on first use.** Rejected — D3. It is how the UI-created organization gets in, and it leaves existence undeclared.
