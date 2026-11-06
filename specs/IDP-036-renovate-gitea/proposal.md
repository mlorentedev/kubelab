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

- **Trigger.** A systemd timer runs a oneshot service that starts the Renovate container. It is set to `OnCalendar=hourly` with `Persistent=true`: it runs every hour while the node is up, and once at boot when a run was missed while it was off. That one setting covers both the hourly cron and the dispatch at boot. The service is ordered after the forge's compose unit, but `After=` only orders units started together, so it does not guarantee Gitea is up when the timer fires. The service therefore probes Gitea first. If Gitea does not answer within a bounded wait, the service logs a skip and exits 0 without starting Renovate. A forge that is stopped while the node is up then fails nothing either. systemd never starts a oneshot unit that is already running, so a slow run cannot overlap the next one.
- **Repositories.** `RENOVATE_REPOSITORIES` is rendered from `apps.services.core.gitea.organizations`, so it is never a second list.
- **Shared config.** The generic settings live in one preset in the `ci-workflows` repository on GitHub, shared by every repository on both forges (owner decision 2026-11-05: "lo de renovate ... que funcione en todos los repos de las dos forjas"). The `ci-workflows` session owns the preset and the GitHub side. On Gitea, one global config file rendered by Ansible holds `extends: ["github>mlorentedev/ci-workflows//<preset>#<tag>"]` with the tag pinned, plus `onboarding: false` and `requireConfig: optional`. Renovate documents that combination as "repository is processed regardless of config file presence" (self-hosted configuration, `requireConfig`). So no Gitea repository holds a copy or a reference line, and the preset lives on GitHub, so no sixth Gitea repository is needed (ADR-065 D5). A repository may still add a `renovate.json` to override the shared config.

  This amends this spec's first decision (2026-11-03), a global config with the settings inline and no preset. The owner chose `extends` with a pinned tag over an Ansible-vendored copy: one copy only, and Renovate bumps the tag like any other dependency. The cost is that each run reads the preset from GitHub, which the node already reaches for registries. The preset carries the generic settings (`vulnerabilityAlerts` on its own schedule, `groupName` per ecosystem, the Dependency Dashboard on) and never the repository-specific custom managers. Automerge is not in it, because it is forbidden in every repository; every PR is merged by a person.
- **Identity.** A dedicated Gitea account, minted and recorded in SOPS the way the role already handles its other tokens (a mint in the container, then a record in SOPS). The mint is gated on the SOPS entry being absent (`when: not <token var>`, the pattern the provisioning token uses), so a re-provision mints nothing and still reports `changed=0`. It is a member of each declared organization with `write`, and owns nothing (ADR-065 D1).
- **Engine version.** One home, in `ci-workflows` next to the preset (owner decision 2026-11-05), bumped by that repository's own Renovate. Every GitHub caller takes it from the reusable workflow and pins nothing. The Gitea run reads it from `ci-workflows` at the same pinned tag as the preset, so kubelab pins one thing, that tag, for both. A `common.yaml` key for the engine (#3110) is not added: it would be removed as soon as the version moved.

This deviates from the ticket's K3s CronJob, and from this spec's first draft, which put the run on a Gitea Actions schedule. The design note on #1384 rejected a CronJob on the always-on VPS because it would fire against a powered-off forge. A timer on the forge's own node keeps that property: when the forge is off, nothing fires and nothing fails. It also needs no workflow repository, which the reconciler cannot create (ADR-065 D5).

## Out of scope

- Vulnerability scanning: Renovate updates, Trivy detects (#1383).
- The GitHub repository (#2931) and operator manifests (#694).
- Gitea Actions as CI for these repositories (#504), which gates the value of the PRs but not this mechanism.

## Risks / open questions

- **#2931 dependency: resolved.** It is proven on GitHub: dashboard #2952, PRs #2950, #2951 and #2957 merged.
- **Ticket AC1 (is the set worth a job): resolved.** `apps.services.core.gitea.organizations` declares five repositories, and openkm-brain already holds unpatched advisories (teledyne/openkm-brain#37). The ticket's prerequisite #1076 (TOOL-035), the declarative path that puts repositories into Gitea, is closed.
- **Timed or triggered: resolved.** It is both, through `OnCalendar=hourly` and `Persistent=true` (see Design).
- **Home of the workflow and preset: resolved.** The Gitea run is the `beelink_services` role. The preset is in `ci-workflows` on GitHub (see Design).
- **Reach across organizations: resolved.** The preset is in a public GitHub repository, so every Gitea organization reads the same one. The bot's organization membership is declared alongside the other identities.
- **Open: reading a `github>` preset from a Gitea run.** Renovate fetches it through the GitHub API, where an unauthenticated client gets 60 requests an hour. Prove it with a dry run against one Gitea repository before the timer lands, and add a read-only `github.com` host rule if the run needs it.
- **The PRs land with no CI on the forge.** Gitea Actions CI for these repositories is #504, out of scope here. Until it exists, a person reviews each Renovate PR, which the no-automerge rule already requires. #504 bounds how much a PR is worth, not whether this mechanism works.
- **Open: run length on the 8 GB node.** One run covers five repositories next to the forge and its runners. The memory limit on the container and the measured duration of a full run go on #1384 after the first run.

## Acceptance criteria

- [ ] The repository list is derived from `apps.services.core.gitea.organizations`, never hand-listed. A test renders the role's template and compares it against the SSOT.
- [ ] A systemd timer in `beelink_services` (`OnCalendar=hourly`, `Persistent=true`) starts the run only once Gitea answers, and skips with exit 0 when it does not. A powered-off node fires nothing, a stopped forge on a running node fails nothing, and the second provision run reports `changed=0`.
- [ ] One shared preset in `ci-workflows`, used on Gitea through a global config rendered by Ansible that `extends` it at a pinned tag, with `onboarding: false` and `requireConfig: optional`. The preset sets `vulnerabilityAlerts` on its own schedule and `groupName` per ecosystem, with no automerge. No Gitea repository holds a copy.
- [ ] The Renovate engine version lives only in `ci-workflows`. The Gitea run reads it at the pinned `ci-workflows` tag, and kubelab carries no engine version of its own: a test fails on a literal one in the role or in `.github/workflows/renovate.yml`.
- [ ] The Dependency Dashboard is on, and PR volume over the first two cycles is recorded on #1384.
- [ ] The bot account and its token go through SOPS and the rotation catalog, on their own identity.
- [ ] The dead `dependabot.yml` files in fae-brain, openkm-brain and resume are removed (#2140).

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADRs: ADR-028 (placement), ADR-061 (forge on Beelink), ADR-065 D1 and D5 (repository reconciler)
