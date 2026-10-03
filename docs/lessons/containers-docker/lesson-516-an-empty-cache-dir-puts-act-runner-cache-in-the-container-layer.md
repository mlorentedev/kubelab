---
id: lesson-516-an-empty-cache-dir-puts-act-runner-cache-in-the-container-layer
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, act-runner, gitea, volumes]
---

# An empty `cache.dir` puts act_runner's cache in the container layer, while two documents said it was in the volume

**Context**: the Gitea Actions runner on the Beelink mounts `act_runner_data:/data`. The
template comment said "the cache lives inside this container's own volume", and the
backup exclusion in `common.yaml` described that volume as holding the `.runner`
registration file and the actions/cache directory.

**Problem**: neither statement was true. The rendered config left `cache.dir` empty.
act_runner 0.2.13 then uses `$HOME/.cache/actcache` (its `config.example.yaml`), and the
image declares no `USER`, so the path was `/root/.cache/actcache`. That is the
container's writable layer. Measured before the fix: 4.5M there, and `/data/cache` did
not exist. The cache was lost on every container recreation (image bump, compose
change), and its disk use never showed under `docker volume ls`. The backup exclusion's
ruling was still right. What it described was not.

**Solution**: `cache.dir: /data/cache` in `act-runner-config.yaml.j2` (#1960).
`tests/test_gitea_actions_runner.py` asserts that `cache.dir` sits under the path where
`act_runner_data` is mounted, read from the rendered compose. It failed before the
template change. After `make provision NODE=bee ENV=prod`: `/data/cache` on the volume
holds `bolt.db`, the old path is gone with the recreated container, and the second run
reports `changed=0`. Not yet shown: a cached workflow run writing an entry.

**Rule**: an empty config key is a decision too, made by the upstream default. Before
writing down where a service keeps its data, read that default and resolve `$HOME` for
the image's user. Then assert the path against the mount point, not against a comment.

**Tags**: `#act-runner` `#volumes` `#defaults` `#pr-1960`
