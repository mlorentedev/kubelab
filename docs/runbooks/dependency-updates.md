---
id: dependency-updates
type: runbook
status: active
created: "2026-06-14"
owner: manu
---

# Dependency & Security Updates

> How dependency and security updates are opened, triaged, and applied to production in this
> repo. Dependabot only *opens* PRs — applying them (merge → release → deploy) is a separate,
> supervised step. Config SSOT: [`.github/dependabot.yml`](../../.github/dependabot.yml).

## Mental model: two clocks

Security and version updates run on different schedules. Do not conflate them.

| Update type | When it opens | Handling |
|-------------|---------------|----------|
| **Security** (CVE/advisory) | **Real-time** — as soon as the advisory is published. Ignores the schedule. | **Expedited.** Review and apply the same day; do not wait for the weekly batch. |
| **Version** (routine minor/patch/major) | **Weekly** batch (Monday), per `schedule.interval`. | Reviewed in the weekly triage ritual below. |

Weekly is deliberate: daily is noise, monthly lets drift accumulate. A predictable Monday batch
is reviewable in one sitting.

## Scope: which ecosystems get what

`.github/dependabot.yml` declares every ecosystem. Security updates flow everywhere regardless of
this file. Scheduled *version* updates are scoped to code that stays in L0; departing apps rely on
security updates only (set with `open-pull-requests-limit: 0`, which keeps security + `ignore`
rules active while disabling version PRs).

| Ecosystem | Directory | Lifecycle | Version updates |
|-----------|-----------|-----------|-----------------|
| github-actions | `/` | stays in L0 | on |
| docker | `edge/errors` | stays (edge service) | on |
| pip / Poetry | `/` (toolkit) | active L0 CLI | on |
| npm | `apps/web/*` | departs (kubelab.live / mlorente.dev) | security-only |
| gomod | `apps/api/src` | departs | security-only |
| docker | `apps/web`, `apps/api` | departs | security-only |

> Astro majors are pinned on the web apps (`ignore` in the npm block) until `@astrojs/mdx`
> supports Astro 6. Remove that ignore at migration time.

## How updates are applied — by risk tier

> **Auto-merge is forbidden in this repo** (see `CLAUDE.md`). The industry default of
> auto-merging green patch/minor PRs does **not** apply here. Every merge is supervised.

| Tier | Examples | Action |
|------|----------|--------|
| **patch + minor** (grouped) | `web-minor-patch`, `go-minor-patch`, `actions-all` | Review the grouped PR, confirm CI green, squash-merge. Low risk. |
| **major** | typescript 5→6, eslint 9→10, node 22→26 | Manual review always. Expect breaking changes / code edits. Merge only after the app builds and tests pass; otherwise close. |
| **security** | any advisory-driven bump | Expedited — handle the day it appears, out of band from the weekly batch. |

## Service images: Renovate, not Dependabot

Dependabot parses Dockerfiles. The third-party service images live as pinned
tags in `infra/config/values/common.yaml`, so it cannot see them and they were
bumped by hand (#974). Renovate's regex manager reads them; config in
`renovate.json`, coverage asserted in `tests/test_renovate_image_coverage.py`.

**A regex manager fails by silence.** A pattern that matches nothing produces no
error, no PRs, and a dashboard that looks like everything is current. The test
is therefore exhaustive in both directions: no image may be untracked, and none
may be ignored without appearing in `ignoreDeps` where a reader sees the
decision.

### Five images are not tracked, and the reason is tag shape

| Image | Why |
|---|---|
| `cloudflare/cloudflared:latest` | no version to compare |
| `fbonalair/traefik-crowdsec-bouncer:latest` | same |
| `grafana/grafana-oss` | **no tag at all** |
| `myoung34/github-runner:ubuntu-noble` | distro codename, rolls in place |
| `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` | timestamp, not a version |

Give any of them a real tag and the guard forces the decision rather than
leaving it ignored out of habit.

### Three need care, each for a different reason

**Headscale.** Its clients are the Tailscale daemons on eight nodes, pinned
separately and *not* tracked here — so a server bump can outrun them. It is also
the bootstrap dependency for the mesh: if the control plane rejects its clients,
the VPN used to reach the VPS and fix it is the thing that broke. Reach the VPS
by its **public IP**, not the mesh, when working on it.

**Postgres.** A major is not an upgrade. The on-disk format changes and the new
binary refuses the old data directory — it is `pg_dump` on the old version and
restore on the new. Renovate cannot know that and would offer it as one more
bump, so majors need dashboard approval.

**Authelia.** It guards everything behind ForwardAuth, Argo CD included. A
failed schema migration locks the operator out of the tools needed to roll it
back. Confirm a current backup of `authelia-data` first — it holds the session
and WebAuthn store.

For all three: `make backup-coverage ENV=prod` before merging. That is a real
check now rather than an incantation — Authelia and n8n have offsite copies and
Gitea's restore has been exercised (BACKUP-044).

### A Renovate PR will fail CI until the images are synced

`check-config-drift` compares `common.yaml` against
`infra/k8s/base/kustomization.yaml`, and Renovate edits only the first. That red
is the guard working:

```bash
make sync-k8s-images && git commit -am "chore: sync image tags"
```

Staging first, always: ace1 runs `selfHeal: false` precisely so a deploy from a
worktree persists long enough to test against.

## The apply chain (merge → production)

Merging a dependency PR does not by itself ship it. For **runtime** dependencies the change reaches
the cluster through the existing release + GitOps pipeline:

```text
squash-merge fix(deps): …
  → release-please cuts a release (fix = patch bump)
    → multi-arch image rebuild (amd64 + arm64)
      → Argo CD syncs the new image to the cluster (prod selfHeal)
```

This is why commit prefixes matter (set in `dependabot.yml`):

- **`fix`** for runtime deps → release-please rebuilds and deploys the image.
- **`chore`** for dev-dependencies → stops at merge (no release, no deploy needed).
- **`ci`** for github-actions → no release.

`chore:`-prefixed bumps do **not** trigger a release (release-please ignores `chore:`). If a
runtime dependency lands as `chore:` it will merge but never reach the running container — verify
the prefix on runtime bumps.

## Weekly triage ritual (Monday, ~10 min)

1. List the batch: `gh pr list --label dependencies --state open`.
2. **Grouped minor+patch** PRs with green CI → squash-merge.
3. **Major** PRs → open each, read the changelog, decide: review-and-merge if trivial, otherwise
   close (it re-opens next cycle if still relevant) or schedule the migration work.
4. **Security** PRs are not part of this ritual — they are handled the day they appear.
5. Mind the single self-hosted runner: merge in small waves so the CI queue drains. Grouping keeps
   the per-cycle PR count low by design.

## Dependabot commands (comment on the PR)

| Comment | Effect |
|---------|--------|
| `@dependabot rebase` | Rebase the PR on the latest base branch. |
| `@dependabot recreate` | Rebuild the PR from scratch (re-resolves the lockfile). |
| `@dependabot ignore this major version` | Decline this major and stop re-proposing it. |
| `@dependabot ignore this dependency` | Stop all updates for this dependency. |

Dependabot auto-rebases open PRs when the base branch moves; no manual update-branch needed.

## Bitácora visibility (by policy)

Dependabot PRs are **intentionally kept off** the bitácora board (`add-to-project.yml` skips
`dependabot[bot]`). The board tracks planned human work; dependency churn is tracked via the
`dependencies` label and the repository's Dependabot / Security tab. This is a policy choice, not a
limitation to fix.

## Related

- Config: [`.github/dependabot.yml`](../../.github/dependabot.yml)
- CI routing and release flow: [`cicd.md`](cicd.md)
- Secrets policy (why Dependabot PRs lack repo secrets): [`sops-and-secrets.md`](sops-and-secrets.md)
