---
id: lesson-759-a-job-output-built-from-a-secret-is-dropped
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, secrets]
---

# A job output built from a secret is dropped, and its consumer reads an empty string

**Context**: `ci-publish.yml` named the image `${{ secrets.DOCKERHUB_USERNAME }}/kubelab-<app>`
and exported it as the job outputs `registry_url` and `full_image`, which
`notify-build-completion` put in the build notification. Moving the build to
ci-workflows' `docker-publish.yml` (CI-010) meant passing the image name as a
`with:` input, which cannot read `secrets` at all.

**Problem**: The outputs had never reached the notification. The runner drops any
job output whose value contains a secret, with only a warning in the producing
job's log: `Skip output 'registry_url' since it may contain secret.` The
consumer gets an empty string and nothing fails. Measured on staging-deploy run
43637117077 (2026-11-14): the notify job's env shows `IMAGE:` and `REGISTRY:`
empty, so every build notification said "pushed to" with no image named.

**Solution**: Build the name from non-secret context. The tags job now writes
`docker.io/${OWNER}/${REGISTRY_PREFIX}-${APP}` with `OWNER` from
`github.repository_owner`, the namespace the manifests already pin
(`docker.io/mlorentedev/kubelab-*`). `tests/test_ci_publish_shared.py` runs the
step and asserts the name.

**Rule**: Never derive an output, an input or a name another job reads from a
secret, even one that is not sensitive in itself, like a registry username.
Where a value is both public and stored as a secret, take it from `vars` or the
`github` context. Look for `Skip output` warnings in the log when an output a
later job reads comes up empty.

**Tags**: `#github-actions` `#ci-010`
