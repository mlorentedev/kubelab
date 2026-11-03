---
id: "IDP-036-renovate-gitea"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-11-01"
issue: "mlorentedev/kubelab#1384"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Owner decision 2026-11-02: start while Renovate is being made to run; 13 active specs (13 active, limit 10, 2026-11-01)"
---

# IDP-036-renovate-gitea

> **Naming**: file lives at `<repo>/specs/IDP-036-renovate-gitea/proposal.md`. `IDP-036-renovate-gitea` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1384: IDP-036: no dependency-update automation exists for Gitea-hosted repositories -->

Gitea has no Dependabot, so the five repositories declared in `apps.services.core.gitea.organizations` get no dependency PRs, and their `.github/dependabot.yml` files are dead. openkm-brain already holds unpatched advisories (teledyne/openkm-brain#37).

## What

A scheduled Renovate run opens dependency PRs on every declared Gitea repository, from one shared preset, with a Dependency Dashboard on each. It uses the engine and pins #2931 proves on GitHub, so both forges run one mechanism.

## Out of scope

- Vulnerability scanning: Renovate updates, Trivy detects (#1383).
- The GitHub repository (#2931) and operator manifests (#694).
- Gitea Actions as CI for these repositories (#504), which gates the value of the PRs but not this mechanism.

## Risks / open questions

Unresolved, so `tasks.md` waits for them:

- **Depends on #2931.** Start only after a real dashboard or PR on GitHub, since `renovate.json` was never exercised by an engine.
- **Timed or triggered.** Gitea's scheduler does not backfill, and the forge is on-demand, so a daily cron may rarely meet uptime. Options: an hourly cron bounded by Renovate's `schedule`, a dispatch at node boot, or both.
- **Home of the workflow and preset.** The reconciler never creates a native repository (ADR-065 D5), so a new `org/renovate-config` declared first turns `make gitea-reconcile` red. Name an existing repository, or have the operator create the new one before it is declared.
- **Reach across organizations.** The `local>org/repo` preset must be readable from `teledyne` and `personal`.

## Acceptance criteria

- [ ] The repository list is derived from `apps.services.core.gitea.organizations`, never hand-listed.
- [ ] Runs on a Gitea Actions schedule on the Beelink runner, so a powered-off forge fires nothing and fails nothing (deviates from the ticket's CronJob on purpose: ADR-061, the design note on #1384).
- [ ] Repositories reference one shared preset; none copies it.
- [ ] Dependency Dashboard is on, and PR volume over the first two cycles is recorded on #1384.
- [ ] The bot account and token go through SOPS and the rotation catalog (`SecretSpec.forge_actions`), on their own identity.
- [ ] The dead `dependabot.yml` files in fae-brain, openkm-brain and resume are removed (#2140).

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
