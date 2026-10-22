---
id: lesson-618-a-bind-mount-on-colima-ignores-ownership-so-a-container-uid-guard-goes-red-only-on-linux
type: lesson
status: active
created: "2026-10-22"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, testing, mutation]
---

# A bind mount on Colima ignores ownership, so a container-uid guard goes red only on Linux

**Context**: #1876 moved the Argo CD RBAC evaluator run from a test into
`toolkit/features/access_review.py`. The image runs as uid 999, so the
`docker run` passes `--user $(id -u):$(id -g)`. Without it the container cannot
enter the 0700 directory `tempfile.TemporaryDirectory` creates, and every case
answers No.

**Problem**: `make mutate` removed `--user`, and the integration test stayed
green on the Mac. Colima shares `$HOME` into its VM through a mount that does
not enforce the host's owner and mode, so uid 999 reads the 0700 directory
anyway. On a Linux runner the bind mount keeps the host's uid and mode, and the
same mutant answers No to every case.

**Solution**: Keep `--user`. The guard is the integration test as CI runs it:
`make test` includes the `integration` marker, on a Linux runner. The mutation
proof is recorded in the PR as host-dependent, not as passed.

**Rule**: A mutation that survives on macOS is not evidence a guard is vacuous
when what it mutates is file ownership or mode across a bind mount. Prove those
on a Linux host, or say the proof was not run. Never drop the flag because the
Mac did not need it.

**Tags**: `#docker` `#colima` `#mutation-testing` `#issue-1876`
