---
id: lesson-598-a-workflow-ports-to-gitea-unless-it-uses-github-as-a-platform
type: lesson
status: active
created: "2026-08-27"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitea, act-runner, forge]
---

# A workflow ports to Gitea Actions unless it uses GitHub as a platform

**Context**: TOOL-035 migrated `mlorentedev/resume` into the Gitea forge on the Beelink and had to
predict, before the migration, which of its five workflows would still run on `act_runner`.

**Problem**: The expected constraint was marketplace availability, and it turned out not to be the
constraint. Gitea resolves `uses:` against github.com by default, so `actions/checkout`, `hadolint`,
`docker/*`, `astral-sh/setup-uv`, `actions/setup-python` and `aquasecurity/trivy-action` all ran.
The three workflows that failed were the ones that call the GitHub API as a platform:
`release-please-action` opens PRs and releases through `api.github.com`, and `add-to-project` and the
bitácora status job write to GitHub Projects through GraphQL. A compatibility list would have
predicted none of this.

**Solution**: Classify each workflow by what it talks to before migrating. `ci.yml` and
`publish-drive.yml` only talk to the runner and to their own secrets, so they moved and `ci.yml`'s
six jobs went green (run 9, 2026-09-04). The other three were recorded as an accepted loss with a
tracker each: release on kubelab#1624, the two board integrations on `personal/resume#260`.

**Rule**: Ask "does this step call the forge's API, or only run on the runner?" A step that only runs
on the runner ports to Gitea. A step that creates releases, PRs, project items or check runs through
`api.github.com` does not port, whatever the action is called. Each such step needs a replacement
or a written decision to drop it before the migration starts.

**Tags**: `#gitea` `#act-runner` `#spec-tool-035` `#pr-1597`
