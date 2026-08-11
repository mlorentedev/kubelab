---
id: "adr-059-retire-calver-release-bundle"
type: adr
status: accepted
created: "2026-08-11"
tags: [architecture, ci-cd, versioning, release-please]
related:
  - adr-044-unified-notification-routing-fabric
  - adr-046-gitops-delivery-promotion-strategy
  - adr-056-build-once-monorepo-apps
issue: "mlorentedev/kubelab#564"
---

# ADR-059: Retire the CalVer global release bundle

## Status

Accepted — 2026-08-11

## Context

Two independent mechanisms ran on every push to `master`, both capable of producing a GitHub
Release:

- `release.yml` (release-please) — per-component semver (`api-vX.Y.Z`, `errors-vX.Y.Z`), but
  a release only cuts when conventional commits touching that component's path warrant a
  bump, with a real changelog. This is the sole semver authority per
  [ADR-046](adr-046-gitops-delivery-promotion-strategy.md) D2.
- `ci-release.yml` ("Create Global Release Bundle") — unconditional: a release on every push,
  no gate, tagged `vYYYY.MM.DD[-HHMMSS]`, with a zip of `Makefile` + `infra/` + `toolkit/` +
  compose files attached, and instructions to `unzip && make deploy`.

`ci-release.yml` predates the K3s/Argo CD migration. Its own deploy instructions no longer
match the GitOps pull model (Argo CD syncs manifests directly from git; `make deploy` is not
the K3s deployment path) — tracked as open debt since 2026-06-11 (`#564`, VER-006) and flagged
again in the 2026-07-07 docs audit (D62) as a second live release mechanism diverging from
ADR-046. [ADR-056](adr-056-build-once-monorepo-apps.md) explicitly deferred the decision to
"a separate audit ticket" — that ticket is `#564`.

Left running, it fired on every merge to master (including routine dependabot bumps),
producing one release + one zip artifact per push. By 2026-08-11 this had accumulated 309
`v2026.*` tags/releases, none referencing anything a consumer pinned to.

## Decision

Retire `ci-release.yml`. No replacement bundle.

**Rationale — pin vs. HEAD.** A component earns a semver release when something else
references it *by a fixed version*: `apps/api` and `edge/errors` are pinned by tag in
`infra/k8s/base/kustomization.yaml`, so they keep release-please. Nothing pins to a version
of `infra/` or `toolkit/` — Argo CD syncs `infra/k8s` from git at whatever commit is on
`master`; the commit SHA already is the version. Ansible and the toolkit CLI run against
checked-out `HEAD`. A CalVer tag added no information a `git log` didn't already have, and
the zip's deploy story (`make deploy`) was stale.

The 309 accumulated `v2026.*` tags/releases were deleted (both the GitHub Release objects
and the underlying tags) as pure noise. `api-v*`, `errors-v*`, and the `web-v*` tags left
over from the extracted `web` repo (ADR-048) were left untouched.

As part of this change, `ci-publish.yml`'s `notify-build-completion` job — cited in
[ADR-044](adr-044-unified-notification-routing-fabric.md)'s reference audit (R2) as an
"ad-hoc" pre-fabric source — was migrated to the normalized envelope contract
(`{domain, severity, title, body, source}`, `domain: "dev"`, `severity: "log"` per ADR-044's
own delivery-need row for this source: "push on failure, log on success"). This job only
runs on success, so no push tier is needed. **Not yet resolved by this change:** the n8n
routing table has no Slack destination in the repo-managed Apprise SOPS config
(`apps.services.automation.apprise.*` covers Telegram only), and the n8n workflow content
itself lives outside git (`APP-CONFIG-003` pending). Wiring `domain: "dev"` to a Slack
Apprise destination is a manual n8n-side step, tracked as follow-up, not part of this ADR.

## Consequences

**Positive**
- One release mechanism (release-please), matching ADR-046's "sole semver authority."
- No release/zip noise on routine pushes (e.g., dependabot merges).
- Closes `#564`.

**Negative / accepted**
- The "download a zip and deploy on a fresh box without git" path no longer exists. Nothing
  in the repo's runbooks referenced it (verified by grep before retirement). If a genuine
  air-gapped/offline-install need ever appears, it is a new decision, not a revival of this
  mechanism — the `make deploy` instructions it shipped were already wrong for the current
  K3s/Argo CD deploy path.
- `infra/` and `toolkit/` changes have no changelog or tagged release. If wanted purely as a
  showcase/communication device (this is a public portfolio repo) rather than a technical
  need, that is a separate, optional follow-up: two additional release-please components
  (`infra`, `toolkit`, kept apart to avoid double-counting commits already attributed to
  `apps/api`/`edge/errors`), same accumulate-then-human-merge flow already in use.

## Alternatives Considered

- **Keep it, gate on real changes only.** Still two release mechanisms to maintain, and the
  `make deploy` staleness would need fixing anyway. Rejected — no consumer justifies the
  upkeep.
- **Fold into release-please as a root (`.`) package.** Would double-count commits already
  attributed to `apps/api`/`edge/errors` (both are subtrees of `.`), reintroducing per-push
  noise on every app change. Rejected; see *Consequences* for the non-double-counting
  alternative if a showcase release is wanted later.

## References

- [ADR-044](adr-044-unified-notification-routing-fabric.md) — envelope contract, R2 reference
  row.
- [ADR-046](adr-046-gitops-delivery-promotion-strategy.md) D2 — release-please as sole semver
  authority.
- [ADR-056](adr-056-build-once-monorepo-apps.md) — deferred this decision to a "separate audit
  ticket."
- `#564` (VER-006) — the deferred ticket, closed by this ADR.
