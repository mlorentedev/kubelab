---
id: lesson-671-an-image-is-fetched-by-whatever-needs-it-not-only-by-a-pull
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, docker, lab-edge]
---

# An image is fetched by whatever needs it, not only by a pull

**Context**: Behind the lab edge every image fetch shares the shaped uplink (ADR-075), so `_includes/image-pull.yml` sizes a pull before it starts (#2742). `tests/test_image_pull_budget.py` held every role behind the edge to it by looking for tasks that pull: a command with `pull` in it, or a `community.docker` module that fetches unless told `pull: never`.

**Problem**: dockerd fetches a missing image for any command that needs one. `docker run` and `docker create` do unless given `--pull never`, and a buildx `docker-container` builder fetches BuildKit's image when it is bootstrapped. None of these says `pull`, so the guard passed four fetches it had never seen (#2822): the agent_stack probes (busybox), the docker role's `hello-world` check, and beelink_services' `docker run multiarch/qemu-user-static`, unpinned. One of them did not need to exist at all. On Ubuntu 24.04 the `qemu-user-static` package ships its registrations in `/usr/lib/binfmt.d` and systemd-binfmt loads them, with the `F` flag a container needs. bee proved it (2026-10-30): `qemu-aarch64` registered with `interpreter /usr/libexec/qemu-binfmt/aarch64-binfmt-P`, `flags: POF`, and no multiarch image in its store. The task ran only when that registration was missing, and then fetched an image to redo the package's work.

**Solution**: The guard reads the image each task runs, keyed by role and image, so a ledgered role that runs a new image fails too. The two small images stay listed with their size. The qemu task restarts systemd-binfmt when the registration is missing. Then, on every run, it reads the registration back and requires the `F` flag. The first version checked only inside the restart's block, and that block never runs on a node that already has a registration, bee included. Ansible's `docker buildx create` without `--bootstrap` fetches nothing (bee's `multiarch` builder is still `inactive`), so it is not a fetch at play time and is not listed.

**Rule**: A guard over a side effect matches the effect, not the verb that usually causes it: here, "this task needs an image the daemon may lack". And before sizing an unwanted fetch, check whether the node already has what it fetches for. A check that a result is right goes outside the block that creates it: inside, it never runs where the result already exists.

**Tags**: `#docker` `#lab-edge` `#issue-2822` `#issue-2742`
