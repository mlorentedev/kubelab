---
id: lesson-243-2026-03-30-fromjson-repo-variable-pattern-for
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-30: fromJSON repo variable pattern for hybrid runner fleets

**Pattern:** `runs-on: ${{ fromJSON(vars.RUNNER_DOCKER || '"ubuntu-latest"') }}`

- Variable unset → `fromJSON('"ubuntu-latest"')` → string `ubuntu-latest`
- Variable = `["self-hosted","linux","docker"]` → `fromJSON(...)` → array with labels

**Security:** Fork PRs MUST be forced to GitHub-hosted: `github.event.pull_request.head.repo.fork && 'ubuntu-latest' || fromJSON(...)`. Self-hosted runner with Docker socket = host-level access.

**Rule:** Use YAML `>-` folded scalars when `runs-on` expressions exceed yamllint line-length limits. GitHub Actions correctly evaluates folded expressions.
