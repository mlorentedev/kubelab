---
id: lesson-308-containers-keep-running-with-no-published-por
type: lesson
status: active
created: "2026-08-10"
owner: manu
tags: [kubelab, lesson, docker, ufw, iptables, live-restore, silent-failure, false-positive, confounded-control, glances, ops-016, gotcha]
---

# Containers keep running with no published ports, and every restart reports success

**Context:** The homepage cockpit showed every Glances widget dark. The obvious reading was that the on-demand nodes were powered off.

**Problem:** All seven nodes were up. Glances answered on two. Probing further, `iptables -t nat -S DOCKER` returned only `-N DOCKER` — the chain present with zero rules — on ace1, ace2, beelink, rpi4 and vps. Every Docker-published port on those five nodes was unreachable: Glances everywhere, MinIO on beelink. Nothing reported an error. `docker ps` listed the containers, `docker inspect` reported correct `PortBindings`, the processes inside were listening, and the healthchecks passed. The only node whose rules were intact, rpi3, was the only node without ufw.

`systemctl restart docker` did not repair it. Neither did `docker restart <name>` — rc=0, chain still empty. A throwaway container with a published port, however, got its DNAT rule created normally on *both* a broken node and the healthy one.

**Solution:** The damage is per container, not per daemon. Containers that survived a daemon restart via `live-restore: true` lost their rules, and restarting them preserves the network sandbox where the damage lives. Only recreation reprograms them — `docker compose up -d --force-recreate`. Tracked as #959.

The cause of the original flush is **not** settled, and the reason is worth recording: rpi3 lacks `base_system` (so it has no ufw) **and** lacks the `docker` role (so it has no `daemon.json`, so no `live-restore`). Those two differences travel together across the whole fleet, so comparing rpi3 against a ufw node varies two things at once. Matching Docker versions between rpi3 and rpi4 felt like a controlled comparison and was not one.

**Rule:**
- **A container reporting healthy says nothing about whether its port is reachable.** Health probes run inside the container; port publishing is kernel state outside it. Assert the DNAT rule or an external request, never the container's own status.
- **A ufw rule cannot restrict a Docker-published port.** Docker's DNAT is evaluated before ufw's filter chains and `DOCKER-USER` is empty on every node here, so the access control for a container is its bind address and nothing else. Interface-scoped ufw rules on published ports look like protection and are decoration.
- **Before calling a comparison a control, list what else differs between the two sides.** A node that never ran a role differs by everything that role installs, not by the one variable under test.
- Fourth same-day instance of a check that passed *because it could not run*: `ignore_errors: true` on a ufw task whose ufw was never installed; a role invocation missing `tags:` so `TAGS=glances` matched nothing and reported success; a `| head` that truncated the evidence a conclusion rested on; and a corrective Ansible task that reported `changed` while fixing nothing. Extends the 2026-08-09 `CANNOT CHECK` rule from composite commands to **any** gate: require that it has been observed failing at least once.

**Tags:** `#docker` `#ufw` `#iptables` `#live-restore` `#silent-failure` `#false-positive` `#confounded-control` `#glances` `#ops-016` `#gotcha`
