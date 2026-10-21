---
id: lesson-606-a-publish-gated-on-release-created-has-no-retry-and-failed-silently-for-five-releases
type: lesson
status: active
created: "2026-10-20"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, release, ci]
---

# A publish job gated on `release_created` has no retry, and it failed silently for five releases

**Context**: Promoting the API in prod from 1.1.0 to 1.1.6 (#2492). `toolkit deployment promote` refused: `Tag '1.1.6' not found`. Docker Hub held `1.0.0`, `1.1.0` and `1.1.1` only, although GitHub had releases up to `api-v1.1.6`.

**Problem**: `release.yml`'s `publish-api` failed on every API release from 1.1.2 to 1.1.6 (June to October), and nothing noticed. Three defects stacked (#2558):

- The 1.1.6 release ran before staging pinned the API. The re-tag reads `apps.platform.api.version` from `values/staging.yaml` at the run's commit, and that commit had no pin.
- The reason never reached the log. `SHA="$(toolkit ...)"` under `bash -e` exits on the failed substitution, and the toolkit logs to stdout (#2536), so the message went into `$SHA`. The job log read `Process completed with exit code 1` and nothing else.
- The job had no second chance. It was gated on `release_created`, which only the run that creates the GitHub release sees. A re-run checks out the same commit, and `workflow_dispatch` never sets the flag.

**Solution**:

- A `republish_api` dispatch flag runs `publish-api` for the current release, read from `.release-please-manifest.json`. The job refuses if `gh release view api-v<version>` fails.
- It is a flag, not a version input, so a re-publish can never move `:latest` backwards.
- The lookup is now `if ! SHA="$(...)"; then echo "::error::...: $SHA"`, so the reason reaches the log. Measured with a stub that fails like the toolkit: the old form printed nothing and the new one prints the message.

**Rule**:

- A job that only the creating run can trigger needs a dispatch path from day one. Otherwise its first failure is permanent.
- Never capture a command with `VAR="$(cmd)"` under `-e` when `cmd` reports errors on stdout. Test the substitution and print the variable on failure.
- A release that publishes nothing should be visible somewhere a person reads, not only as a red job on a push nobody watches.

**Tags**: `#release-please` `#adr-056` `#issue-2558`
