---
id: lesson-124-2026-03-16-ci-cd-release-pipeline-gotchas
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-16: CI/CD Release Pipeline Gotchas

**Lesson: release-please tag format — watch separator + include-v-in-tag**
- **Problem**: `tag-separator: "-v"` + `include-v-in-tag: true` produces double-v tags (`errors-vv0.0.0`)
- **Fix**: Use `tag-separator: "-"` with `include-v-in-tag: true` → produces `errors-v0.1.0`
- **Rule**: Test tag format with `release-please` docs before deploying. The tag format affects all downstream consumers (Docker publish, changelogs, Git tags).

**Lesson: GitHub Actions needs explicit write permissions for release-please**
- **Problem**: `startup_failure` on release.yml — GitHub Actions default permissions are `read`, release-please needs `write` to create PRs
- **Fix**: Settings → Actions → General → Workflow permissions → Read and write. Also `can_approve_pull_request_reviews: true`.
- **Rule**: When adding workflows that create PRs/releases, check repo-level Actions permissions first.

**Lesson: Trivy action versions are unstable — use continue-on-error or remove**
- **Problem**: `aquasecurity/trivy-action@master`, `@0.28.0`, `@0.31.0`, `@0.39.0` all failed with different errors
- **Fix**: Removed entirely. Will re-evaluate when action stabilizes or use CLI-based scanning instead.
- **Rule**: Never pin to `@master` for any GitHub Action. If a pinned version breaks, add `continue-on-error: true` rather than blocking builds.

**Lesson: Helm resource adoption requires clean delete + recreate**
- **Problem**: `kubectl apply`-managed resources have labels incompatible with Helm. Annotating for adoption works but patches fail if port specs differ.
- **Fix**: Delete the resource, let Helm recreate it from scratch. The brief downtime is acceptable for staging.
- **Rule**: When migrating from raw manifests to Helm, plan for resource recreation. Don't try to adopt and patch simultaneously.
