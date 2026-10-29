---
id: lesson-649-a-smoke-build-tests-the-builder-the-shell-selected-not-the-engine
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, buildkit, ansible, ci]
---

# A smoke build tests the builder the shell selected, not the engine

**Context**: #2763 added a smoke build to the provision that upgrades the Beelink's Docker engine, to catch the BuildKit session drops of #2722 before a Gitea job does. It ran `docker buildx build` under a 180 s timeout, as root, in the `docker` role.

**Problem**: The first live run failed with rc 124, and the play reported a dropped BuildKit session. The engine was not involved:

- `docker buildx build` uses the builder selected for the user running it. The `beelink_services` role creates `multiarch` with `docker buildx create --driver docker-container --use`, as root, so root's builds go to a BuildKit container, not to dockerd's own BuildKit.
- `multiarch` was inactive. Starting it meant pulling the `moby/buildkit` image first, over an uplink measured at about 46 KB/s. dockerd logged the pull cancelled by the timeout. The base image the build needed was not present either.
- The Gitea jobs build on `default`. Their job containers have no buildx state of their own, and #2722's `session healthcheck failed` lines are in `journalctl -u docker`, which is dockerd's session manager. A docker-container builder logs those in its own container.

So the check measured a different BuildKit, and charged the uplink's time to it. The fail message then named a cause it had no evidence for.

**Solution**: The smoke build passes `--builder default`. The pinned base image is pulled first in its own task, under the same timeout, with a message that blames the registry or the uplink and says the build did not run. The build's timeout then measures the engine alone. The rc 124 message no longer asserts #2722. It quotes the last lines of the build's output and names the journal line that would confirm a dropped session. `tests/test_docker_smoke_build.py` holds the builder, the order and both messages.

**Rule**: A check for a component names that component. A `docker buildx build` without `--builder` tests whatever `docker buildx use` last chose for that user, and a role elsewhere may have chosen it. Fetch what the check depends on before its timeout starts, so the timeout measures the thing under test. A failure message says what was observed and how to confirm the cause, not the cause it was written to catch.

**Tags**: `#ops-050` `#buildkit` `#docker` `#pr-2771`
