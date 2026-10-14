---
id: add-a-node
type: runbook
status: active
created: "2026-10-14"
owner: manu
---

# Add a Node to the Fleet

> Ansible verifies every stable node's host key against a pinned file and never accepts one unseen (ANSIBLE-066). A node that is not pinned cannot be provisioned, so pinning comes before the first run.

## 1. Declare it

Add the node under `networking.nodes` in `infra/config/values/common.yaml`: `hostname`, `lan_ip`, `location` (ADR-028) and `ansible_groups`. Leave `tailscale_ip` empty until step 5. Every generator reads this block; do not add the node to any other file by hand. Then run `make sync-platform-json`: the public manifest lists the fleet, and CI's `validate-sync` fails until it matches `common.yaml`. The inventory needs no step of its own: `toolkit infra ansible run` regenerates it before every run.

## 2. Verify its host key out of band

On the node's own console (keyboard and screen, or the provider's serial console), read the fingerprint:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Then compare it with what the network presents to the workstation:

```bash
ssh-keyscan -t ed25519 <lan_ip> | ssh-keygen -lf -
```

They must be equal. If they differ, stop: something other than the node answered.

## 3. Pin it

In the dotfiles repo, add one line to `ssh/known_hosts` for the host, with its provenance and fingerprint in the two comment lines above it, as the existing entries do. One line carries every address of the host; for now that is the LAN address. Add a `Host` block in `ssh/config` with `UserKnownHostsFile ~/.ssh/known_hosts_pinned` and `StrictHostKeyChecking yes`. `bats tests/ssh-known-hosts.bats` checks the pair. Merge it, then `dotf converge` on each controller.

The path Ansible reads is `networking.ssh_known_hosts`. `toolkit infra ansible run` refuses to start when that file is missing.

Probe the pin before anything depends on it. The user is `networking.ssh_users.homelab`; the two `Control*` options stop a reused connection from skipping the key check (lesson-569):

```bash
ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=~/.ssh/known_hosts_pinned \
    -o ControlMaster=no -o ControlPath=none <user>@<lan_ip> true
```

Exit 0 means the pinned line matches. "Host key verification failed" means the line is malformed, names another address, or the pin has not been deployed on this controller.

## 4. Provision over the LAN

`NODE` names a playbook, not a host: `make provision NODE=<x>` runs `infra/ansible/playbooks/provision-<x>.yml` (the Beelink's is `provision-bee.yml`, so `NODE=bee`). A new node needs its own: copy the sibling closest to its role, set `hosts:` to the node's `hostname`, and keep its roles to what the node runs.

```bash
make provision NODE=<x> ENV=<env> BOOTSTRAP=1 ASK_PASS=1
```

## 5. Enroll it in Headscale

Join the node to the mesh as `docs/runbooks/headscale-setup.md` describes, then record the address Headscale gave it as `tailscale_ip` in `common.yaml`.

## 6. Regenerate what derives from it

The node's `tailscale_ip` feeds the Headscale ACL host aliases, and `common.yaml` changed again, so render both from the SSOT:

```bash
make sync-platform-json
make deploy TARGET=vps ENV=prod   # Headscale policy: the node's ACL alias
```

The DNS gateway lists nodes by name in the `coredns` role; only when the new node is added there does `make deploy TARGET=dns ENV=prod` apply.

## 7. Pin the mesh address and probe it

Scan the mesh address; it must present the same key as in step 2. Add that address to the node's pinned line, merge, converge, and run the step 3 probe against `<tailscale_ip>` from a controller on the mesh. Later runs use the mesh address.

A run that fails with "Host key verification failed" on this node means the pin is not deployed on this controller, or the node now presents another key: verify it again (step 2) before changing anything.

## The one exception: a node replaced by design

A node declared with `tailscale_dns` and no `tailscale_ip` (the GCP hub) is recreated on every preemption, with a new host key each time, so no pin can hold. The inventory keeps `StrictHostKeyChecking=accept-new` for that node alone, derived from that shape, and `wait-node-ready.yml` forgets its previous key. Host certificates replace both (#1261).
