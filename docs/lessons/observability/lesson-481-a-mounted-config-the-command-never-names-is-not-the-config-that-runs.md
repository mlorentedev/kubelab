---
id: lesson-481-a-mounted-config-the-command-never-names-is-not-the-config-that-runs
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: observability
tags: [kubelab, observability, vector, docker-compose, dev]
---

# A mounted config that the command never names is not the config that runs

**Context**: SEC-021 (#1840) added token redaction to Vector before Loki.
Its follow-up, #1844, brought the same remap to the dev Compose pipeline.
That pipeline mounts `infra/config/loki/vector.toml` into the `loki-vector`
container.

**Problem**: Dev Vector had never shipped a single Docker log to Loki, and
nothing looked wrong. The Compose service had no `command:`, so the image
started with its own default, `/etc/vector/vector.yaml`, which is a demo
config: `demo_logs` events printed to the console. The container was up,
healthy and writing logs, just the demo's. The mounted file was never read,
so it could also be invalid for Vector 0.43 (no `encoding` on the `loki`
sink) without anyone finding out. Editing it, redaction included, changed
nothing that ran.

**Solution**: #1844 added
`command: ["--config", "/etc/vector/vector.toml"]` and
`test_dev_vector_loads_the_mounted_config`, which ties the `--config` path
to the mount target. The test was red first. The mounted file was fixed to
validate (`encoding: text`, the K8s codec), and `vector test` now runs over
both the dev and the K8s config with the pinned image.

**Rule**: A mount puts a file on disk. It does not make the process read it.
For any image that ships a default config, name the mounted path in the
command, and test that the two agree. A running, healthy container is not
evidence of which config it loaded. Look for your own pipeline's output
(here, a Docker log line in Loki) and not for the container being up.

**Tags**: `#vector` `#docker-compose` `#pr-1844` `#issue-1840`
