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

A Renovate run on the Beelink node opens dependency PRs on every declared Gitea repository, all of them from one shared config, with a Dependency Dashboard on each. It uses the engine version #2931 proved on GitHub (dashboard #2952, PRs #2950, #2951 and #2957), so both forges run one mechanism.

## Design

Owner decision 2026-11-03, on #1384. Everything lives in the `beelink_services` Ansible role, so there is one home and no repository to create:

- **Trigger.** A systemd timer runs a oneshot service that starts the Renovate container. It is set to `OnCalendar=hourly` with `Persistent=true`: it runs every hour while the node is up, and once at boot when a run was missed while it was off. That one setting covers both the hourly cron and the dispatch at boot. The service starts after the forge's compose unit and waits until Gitea answers. systemd never starts a oneshot unit that is already running, so a slow run cannot overlap the next one.
- **Repositories.** `RENOVATE_REPOSITORIES` is rendered from `apps.services.core.gitea.organizations`, so it is never a second list.
- **Shared config.** One global config file, rendered by Ansible, carries the repository settings that `renovate.json` holds on GitHub, with `onboarding: false` and `requireConfig: optional`. Renovate documents that combination as "repository is processed regardless of config file presence" (self-hosted configuration, `requireConfig`). So no repository holds a copy, there is no preset repository, and no preset has to be readable across organizations. A repository may still add a `renovate.json` to override the shared config.
- **Identity.** A dedicated Gitea account, minted and recorded in SOPS the way the role already handles its other tokens (a mint in the container, then a record in SOPS). It is a member of each declared organization with `write`, and owns nothing (ADR-065 D1).

This deviates from the ticket's K3s CronJob, and from this spec's first draft, which put the run on a Gitea Actions schedule. The design note on #1384 rejected a CronJob on the always-on VPS because it would fire against a powered-off forge. A timer on the forge's own node keeps that property: when the forge is off, nothing fires and nothing fails. It also needs no workflow repository, which the reconciler cannot create (ADR-065 D5).

## Out of scope

- Vulnerability scanning: Renovate updates, Trivy detects (#1383).
- The GitHub repository (#2931) and operator manifests (#694).
- Gitea Actions as CI for these repositories (#504), which gates the value of the PRs but not this mechanism.

## Risks / open questions

- **#2931 dependency: resolved.** It is proven on GitHub: dashboard #2952, PRs #2950, #2951 and #2957 merged.
- **Timed or triggered: resolved.** It is both, through `OnCalendar=hourly` and `Persistent=true` (see Design).
- **Home of the workflow and preset: resolved.** It is the `beelink_services` role, with no workflow or preset repository (see Design).
- **Reach across organizations: resolved.** There is no preset to reach. The bot's organization membership is declared alongside the other identities.
- **Open: run length on the 8 GB node.** One run covers five repositories next to the forge and its runners. The memory limit on the container and the measured duration of a full run go on #1384 after the first run.

## Acceptance criteria

- [ ] The repository list is derived from `apps.services.core.gitea.organizations`, never hand-listed. A test renders the role's template and compares it against the SSOT.
- [ ] A systemd timer in `beelink_services` (`OnCalendar=hourly`, `Persistent=true`) starts the run after Gitea is ready. A powered-off forge fires nothing and fails nothing, and the second provision run reports `changed=0`.
- [ ] One shared config, rendered by Ansible, with `onboarding: false` and `requireConfig: optional`. No Gitea repository holds a copy.
- [ ] The Renovate image is pinned once in `common.yaml`, at the same version as `.github/workflows/renovate.yml`. A test fails when the two differ.
- [ ] The Dependency Dashboard is on, and PR volume over the first two cycles is recorded on #1384.
- [ ] The bot account and its token go through SOPS and the rotation catalog, on their own identity.
- [ ] The dead `dependabot.yml` files in fae-brain, openkm-brain and resume are removed (#2140).

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADRs: ADR-028 (placement), ADR-061 (forge on Beelink), ADR-065 D1 and D5 (repository reconciler)
