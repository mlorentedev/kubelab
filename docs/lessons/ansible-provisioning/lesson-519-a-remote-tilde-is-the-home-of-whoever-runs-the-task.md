---
id: lesson-519-a-remote-tilde-is-the-home-of-whoever-runs-the-task
type: lesson
status: active
created: "2026-10-04"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, coredns, rpi4, become, idempotence]
---

# A remote `~` is the home of whoever runs the task, so a role that uses one has a result per caller

**Context**: #2039's dry run of `make provision NODE=rpi4 ENV=prod` showed the `coredns` role's three templates diffing against files from March. The DNS gateway had been deployed on 2026-10-02 with `make deploy TARGET=dns`, so the diff should have been empty.

**Problem**: The role kept its stack in `coredns_remote_dir: "~/coredns"`, and two playbooks run it. `deploy-dns.yml` has no `become`, so `~` was `/home/manu` and the live containers ran from `/home/manu/coredns`. `provision-rpi4.yml` sets `become: true` at play level, so the same `~` was `/root`, and the dry run was comparing against a stale `/root/coredns`. Both directories have the basename `coredns`, which Docker Compose takes as the project name. A real apply would have run `up -d` from `/root/coredns`, recreated the live containers on that copy, and the next `deploy-dns` would have moved them back. Each caller was idempotent; together they never converge (lesson-295). It stayed hidden because `provision-rpi4` could not render the role at all until #1982 (2026-10-01).

lesson-242 had found the same mechanism in March, as buildx state split between `/root/.docker` and the user's. Its rule was written for buildx only, so it did not reach a role written later.

**Solution** (ANSIBLE-064, #2053):
- **Absolute path:** the stack moves to `/opt/coredns`, like every other service.
- **Own privilege:** the role wraps its tasks in a block with `become: true`, so the caller's privilege no longer matters.
- **Pinned project name:** the compose file pins `name: coredns`. That keeps the Pi-hole volume `coredns_pihole_data` by declaration, no longer by the accident of a directory's name.
- **Cleanup:** the role removes the two legacy directories only after its waits pass, one of them a DNS query through Pi-hole to CoreDNS.
- **Generic guard:** `tests/test_ansible_remote_paths_absolute.py` fails on any task that runs on a managed node and uses a `~` path, either literally or through a variable defined anywhere. It decides whether a task runs on the controller from the task, its block or its play (`delegate_to: localhost`, `connection: local`, `hosts: localhost`). The fetched kubeconfig stays allowed on those grounds, not by a list of exceptions.
- **Role guards:** `tests/test_coredns_stack_location.py` pins the role's own `become`, the absolute directory and the project name.

**Rule**: On a managed node, write paths as absolute. A remote `~` or `$HOME` expands to the home of the task's effective user, so it changes with `become`, and a role that uses one gives one result per caller. `ansible_env.HOME` is no fix: it is a fact, fixed when facts were gathered and under that run's user, so it can name a different home from the one a later task runs as. And a role that more than one playbook runs should declare the privilege it needs, rather than inherit it. When a lesson finds a mechanism, write its rule at the mechanism's level, not the instance's. The buildx rule could have caught this in March.

**Tags**: `#ansible` `#become` `#coredns` `#idempotence` `#issue-2053` `#issue-2039`
