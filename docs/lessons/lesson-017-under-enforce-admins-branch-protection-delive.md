---
id: lesson-017-under-enforce-admins-branch-protection-delive
type: lesson
status: active
created: "2026-06-15"
owner: manu
tags: [kubelab, lesson]
---

# Under `enforce_admins` branch protection, delivery must be PR-per-update opened with a PAT

**Context**: Both Argo CD apps (staging, prod) watch `master`, which is protected with `enforce_admins` → nobody, not even admins or automation, can push directly. Every deploy is a change to `master`, so every deploy must be a reviewed PR. (Same rework also dropped a broken RC version predictor.)

**Problem**: A delivery mechanism that assumes it can `git push` to the deploy branch breaks under `enforce_admins`. And a CI-opened PR using the default `GITHUB_TOKEN` does **not** trigger `on: pull_request` workflows, so its required checks never run and it can never merge — a silent deadlock. Separately, maintaining an RC version predictor alongside release-please created two semver authorities that drifted (RC behind stable, mis-nested staging override).

**Solution**: ADR-046 PR-per-update — staging auto-opens a deploy PR on each merge (`staging-deploy.yml`); prod opens a gated PR on `workflow_dispatch` (`promote-prod.yml`); both via `toolkit deployment promote`. The PRs are opened with a PAT (`RELEASE_PLEASE_TOKEN`), not `GITHUB_TOKEN`, so their checks run. release-please is the sole semver authority; the RC predictor was deleted.

**Rule**: When the deploy branch is `enforce_admins`-protected, delivery automation must **open PRs, not push** — and open them with a PAT so `on: pull_request` checks fire (a `GITHUB_TOKEN`-opened PR is un-mergeable by design). Keep exactly one semver authority (release-please); never run a parallel predictor that can disagree with it.

**Tags**: `#gitops` `#branch-protection` `#pr-per-update` `#github-token` `#release-please` `#adr-046`
