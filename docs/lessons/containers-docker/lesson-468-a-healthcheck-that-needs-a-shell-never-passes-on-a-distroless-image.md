---
id: lesson-468-a-healthcheck-that-needs-a-shell-never-passes-on-a-distroless-image
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, healthcheck, compose, loki, vector]
---

# A healthcheck that needs a shell never passes on a distroless image, and blocks whatever waits on it

**Context**: Recreating the dev Loki stack from master after #1844, so that dev
Vector would finally load its mounted config.

**Problem**: Vector stayed in `created` and never ran. Its `depends_on` waited
for Loki's `service_healthy`, and Loki's check was `CMD-SHELL wget ... || exit 1`.
`grafana/loki:3.6.4` is distroless: every probe answered `exec: "/bin/sh": stat
/bin/sh: no such file or directory`, while `curl localhost:3100/ready` from the
host returned 200. The service was fine and only the probe was broken. It had been
that way since the pin moved off 3.3.2 (#121). Nobody noticed because the
dev container was created in February and never recreated, so it still ran the
old image, which had a shell.

**Solution**: Remove the healthcheck and depend on `service_started`. Vector
retries its sink, and it has to anyway in K8s, where nothing orders the two and
Loki's readiness is the `httpGet` probe. `tests/test_dev_loki_compose.py` fails on
a `CMD-SHELL` check for Loki, or on Vector gating on its health. After the change:
6 containers and 141 lines in dev Loki within 5 minutes.

**Rule**: A container healthcheck runs inside the image, so it may use only what
the image ships. When bumping an image, check that its healthcheck still has its
tools. A check that can never pass is worse than no check: it measures nothing
and blocks everything ordered after it. Recreate a long-lived dev container after
a pin change, or it keeps testing the old image.

**Tags**: `#healthcheck` `#distroless` `#compose` `#pr-1849`
