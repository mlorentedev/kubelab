# Runbook: GitOps Delivery & Promotion

How code reaches staging and prod. Implements [ADR-046](../adr/adr-046-gitops-delivery-promotion-strategy.md). Both environments are Argo CD Applications watching `master`; nothing is pushed to `master` directly (it is protected) — every deploy is a reviewed PR.

## Model at a glance

| | staging | prod |
|---|---|---|
| Image tag | `sha-<short>` (immutable, per commit) | `X.Y.Z` (immutable semver, release-please) |
| Trigger | auto on every `master` push touching `apps/**` | manual (`promote-prod.yml` workflow_dispatch) |
| Gate | PR auto-opened, you rubber-stamp | PR opened on demand, you review |
| `imagePullPolicy` | `Always` only for mutable tags; `sha-*`/semver → `IfNotPresent` (generator, tag-aware) | `IfNotPresent` |
| selfHeal | false (mutable test bed) | true (system of record) |

Image tags are **never reused as desired state**: a tag change is always a real git diff Argo reconciles. release-please is the sole authority for semver.

### How the prod semver is produced (build-once — ADR-056, `api` only)

When release-please cuts `api:X.Y.Z`, `release.yml` does **not** rebuild. It resolves the staging-validated `sha-<short>` from `values/staging.yaml` (`toolkit deployment image-tag --env staging --app api`) and re-tags that exact digest with `docker buildx imagetools create -t api:X.Y.Z api:sha-<short>` (manifest list copied → byte-identical amd64+arm64). So the bytes prod runs are the bytes a human validated on staging — closing the artifact-parity gap that CrashLooped the first gated promotion (#666 / #679). Parity is verified in-job by digest equality; a mismatch fails the release. **Precondition:** `api` must be pinned to a real `sha-*` in staging (deploy it there first), or the release fails fast rather than ship unvalidated bytes. `errors` is out of scope (edge infra) — it still rebuilds at release. The prune janitor (`ci-cleanup.yml`) never deletes a `sha-*` referenced by a committed overlay, so a pending re-tag can't lose its source.

## Deploy to staging (normal dev loop)

1. Open a feature PR, get it green, merge to `master`.
2. `staging-deploy.yml` fires automatically: builds `kubelab-<app>:sha-<short>` for each changed app, runs `toolkit deployment promote --env staging --app <app> --version sha-<short>`, regenerates the overlay, and opens a PR titled `chore(staging): deploy sha-<short>`.
3. Review (a glance — the diff is the image tag) and **merge** it. Argo CD (staging) syncs and rolls the pods.
4. Verify: `curl -sSI https://staging.mlorente.dev/` → 200, and spot-check the change.

Pre-merge preview (optional): a feature-branch CI build also produces `sha-<pr-short>`; deploy it to staging out-of-band with `make deploy-k8s ENV=staging` (selfHeal:false tolerates it until the next sync).

## Promote to prod (deliberate)

1. Pick the stable version to ship (must already exist as a release tag — check `apps/<app>/version.txt` / the registry).
2. Run the **Promote Prod** workflow (`promote-prod.yml`) via *Actions → Run workflow*, select the `app` and input the `version` (one app per run — web and api carry independent semvers). It runs `toolkit deployment promote --env prod --app <app> --version <X.Y.Z>` and opens a PR `promote: prod <app> to <X.Y.Z>`.
   - Or do it locally: `toolkit deployment promote --env prod --app web --version 1.2.0`, commit the regenerated overlay, open the PR.
3. Review the PR (image diff + any config), ensure staging has validated equivalent code, **merge**. Argo CD (prod, selfHeal:true) deploys and then defends that version.

## Rollback

- **Either env:** `git revert` the deploy/promotion PR merge commit on `master` → Argo reconciles back to the previous tag. Prod self-heals to it immediately.
- Immutable tags mean the previous image still exists; rollback is deterministic.

## Troubleshooting

- **Staging PR checks never run / stuck pending** → the PR must be opened by `RELEASE_PLEASE_TOKEN` (a PAT), not `GITHUB_TOKEN`; a GITHUB_TOKEN-opened PR does not trigger `on: pull_request` checks. Verify the token in `staging-deploy.yml`.
- **`toolkit deployment promote` fails "tag not found"** → the image was not built/pushed yet (registry check is intentional — it refuses to promote a non-existent tag). Re-check the build job.
- **Config-drift gate fails on the deploy PR** → the overlay was hand-edited instead of regenerated. Never edit `infra/k8s/overlays/<env>/generated/` by hand; always go through `toolkit deployment promote` (it regenerates atomically).
- **Pod not picking up a new mutable tag** → only relevant for legacy mutable tags; `sha-*`/semver are immutable so a tag change always forces a pull. The generator sets `imagePullPolicy: Always` only for `dev`/`latest`/`*-rc.*`.
- **Staging drifted from `master`** → expected within ≤1 sync cycle for out-of-band `make deploy-k8s` applies (selfHeal:false). The next `staging-deploy.yml` PR merge re-aligns it.

## References

- [ADR-046](../adr/adr-046-gitops-delivery-promotion-strategy.md) — the decision + the PR-per-update amendment.
- [ADR-037](../adr/adr-037-environment-promotion-strategy.md) — conditional selfHeal; staging as mutable test bed.
- Epic: `mlorentedev/knowledge#94`.
