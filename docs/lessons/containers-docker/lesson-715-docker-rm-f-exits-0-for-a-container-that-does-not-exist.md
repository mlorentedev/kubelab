---
id: lesson-715-docker-rm-f-exits-0-for-a-container-that-does-not-exist
type: lesson
status: active
title: "`docker rm -f` exits 0 for a container that does not exist, so its exit code cannot say whether anything changed"
created: "2026-11-06"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, idempotence, github-runner]
---

# `docker rm -f` exits 0 for a container that does not exist, so its exit code cannot say whether anything changed

**Context**: #3080 turns bee's unused GitHub runner off. Off has to mean absent, because `docker compose up -d` leaves a service the template stops rendering running as an orphan, so the role removes the container itself with `docker rm -f github-runner`. The role already had the same task for act_runner, with `changed_when: rc == 0` and `failed_when` tolerating `No such container`.

**Problem**: On Docker 29.9.2 (bee, measured 2026-11-06) `docker rm -f <missing>` prints nothing and exits 0. `-f` makes a missing container a success, so `No such container` never reaches stderr. With `changed_when: rc == 0`, the task reports a change on every run after the first, and the role can never reach `changed=0`. The act_runner task carried the same defect unseen, since that runner is enabled and the task never ran.

The runner itself showed a second trap. Its image is pinned (`myoung34/github-runner:2.338.0-ubuntu-noble`), but the runner updates itself: it wrote `/actions-runner/bin.2.338.0`, deleted `/actions-runner/bin`, and never finished. A restart reuses the container's writable layer, so the listener never came back (`./bin/Runner.Listener: No such file or directory`, exit 127, `Restarting`). A throwaway container from the same image still listed `bin/`. Only the container's layer was broken.

**Solution**: Judge the removal by what Docker printed: `docker rm` echoes the name of each container it removed, so `changed_when: <var>.stdout | length > 0`. Both absence tasks in `beelink_services` now use it, and `tests/test_github_runner_disabled.py` pins both.

**Rule**: For a command that treats "already in the desired state" as success, the exit code says only that the command did not fail. To tell a change from the converged state, read the output, or check the state before acting. And a pinned image is a pin only if the software inside it cannot update itself. Turn self-update off (`DISABLE_AUTO_UPDATE` for this runner) wherever the pin is meant to hold.
