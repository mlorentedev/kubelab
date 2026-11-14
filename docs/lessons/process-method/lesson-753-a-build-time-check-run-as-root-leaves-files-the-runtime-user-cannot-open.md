---
id: lesson-753-a-build-time-check-run-as-root-leaves-files-the-runtime-user-cannot-open
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: process-method
tags: [kubelab, process-method, console, docker, nginx, pr-3443]
---

# A build-time check run as root leaves files the runtime user cannot open, and only starting the image as that user shows it

**Context**: The console image (`apps/console/Dockerfile`) is `nginx-unprivileged` (uid 101, `pid /tmp/nginx.pid`). It switches to root for `apk upgrade`, runs `nginx -t` to fail the build on a bad config, then drops back to uid 101.

**Problem**: `nginx -t` as root writes `/tmp/nginx.pid` (and its temp dirs) into the image layer, owned by root. The pod then ran nginx as uid 101, which could not open that pid file: `[emerg] open() "/tmp/nginx.pid" failed (13: Permission denied)`, CrashLoopBackOff on the first staging deploy of `sha-7df897b`. The base image is not at fault (`/tmp` is 1777 there, and `edge/errors` starts because it creates its pid file for its own user). The Dockerfile comment promised a read-only root with a tmpfs at `/tmp`, which would have masked the file, but the generated Deployment sets neither. Every static test passed: the config is valid, the image builds, the headers match. Nothing checked that the image starts.

**Solution**: `USER 101` moved before `RUN nginx -t && rm -f /tmp/nginx.pid`, so the check runs as the runtime user and leaves nothing behind. `tests/test_console_image_runs.py` builds the image and starts it as its own user, in the Deployment's shape and with a read-only root plus tmpfs, and asserts `/` answers. Measured red on the old Dockerfile (the pid error above) and green on the new one; the tmpfs variant passes on both, which is why the plain run is the one that matters.

**Rule**: A build step that runs as root and executes the service's own binary writes state the runtime user inherits. Run such checks as the runtime user, and test an image by starting it as that user in the shape the cluster runs it, never by reading its Dockerfile or its config. A comment that says the pod will mask a defect is a claim to test against the generated manifest. The generator half, a `securityContext` and a `/tmp` volume for custom apps, is #3545.

**Tags**: `#docker` `#nginx` `#pr-3443`
