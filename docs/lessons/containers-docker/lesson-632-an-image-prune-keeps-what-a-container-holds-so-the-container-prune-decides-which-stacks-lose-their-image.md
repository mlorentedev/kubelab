---
id: lesson-632-an-image-prune-keeps-what-a-container-holds-so-the-container-prune-decides-which-stacks-lose-their-image
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, docker, node-maintenance]
---

# An image prune keeps what a container holds, so the container prune decides which stacks lose their image

**Context**: `node_maintenance` cleans Docker the same way on every Docker host, on a
timer. Until this change it ran an unfiltered `docker container prune -f`, then
`docker image prune -af`; the filtered command is under Solution. The timer runs
weekly, and daily on CI nodes. Each stack's systemd unit stops it with
`docker compose stop`, so a stopped stack keeps its containers.

**Problem**: On 2026-10-26 ace2 lost the Open WebUI image and its container (#2703).
ace2's maintenance timer ran at 00:41:22 CET, and Docker's `repositories.json` was
written at 00:42. At boot the unit found no image to start and failed, and pulling
about 3 GB again was not possible on the site link. `image prune -a` alone could
not have done it, because it spares any image that a container references, stopped
or not. The step that decides is the container prune before it: it removes every
stopped container, including a stack the node declares but that happens to be
stopped. Once the container is gone, the image is unused, and the image prune
takes it.

**Solution**: Both implementations, the timer script and the Ansible tasks, prune
containers with `--filter "label!=com.docker.compose.project"`. A container created
by compose survives a stop, so its image survives the image prune. CI job
containers, which compose did not create, are still removed, and so are their
images. Measured with Docker 28.3.3 on two throwaway containers that differed only
in that label: the prune removed the unlabelled one and kept the compose one.

**Rule**: In a prune sequence, ask which step makes a resource unreferenced. That
step decides what the later ones may take. Here it was the container prune, not
the image prune, that decided which stacks lost their image. A stack being retired
is removed by the role that owns its node (`docker compose down`), not by a
general prune.

**Tags**: `#docker` `#node-maintenance` `#issue-2703`
