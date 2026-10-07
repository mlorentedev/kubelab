---
id: lesson-525-a-container-on-a-tailnet-node-leaves-as-that-node
type: lesson
status: active
created: "2026-10-06"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, tailscale, docker, rootless, agents]
---

# A container on a tailnet node reaches the tailnet as that node

**Context**: AI-009's spec assumed (R7) that the agent's internet traffic leaves
"through Docker's normal egress, not through the tailnet", so the tailnet ACL
would govern only what its `tag:hermes` sidecar reaches. ace2 is a tailnet node
whose identity is the admin's (ADR-068 D2).

**Problem**: Docker's egress is the host's routing table, and on a tailnet node
that table sends `100.64.0.0/10` to `tailscale0`. On 2026-10-06, a container
started by the agent's rootless daemon (slirp4netns) opened TCP connections to
the VPS's `:22` and `:6443`, ace1's K3s API, the Beelink's Gitea and ace2's Open
WebUI. Each connection carried ace2's identity, which matches every allow rule.
A rootless daemon or a separate Unix user changes who owns the process, not
which tailnet identity its packets carry. Only ace1's LAN address timed out.

**Solution**: Until the sandbox has its own identity (PR 3b), it has no network
(`terminal.docker_network: false`). Measured afterwards: `NetworkMode=none`,
and `connect_ex` to the VPS's `:22` returned 101. The gateway still leaves as
ace2. PR 3b must move it into the sidecar's network namespace or drop its egress
to `100.64.0.0/10`.

**Rule**: On a node that is a tailnet member, treat every container's egress as
that node's tailnet identity, never assume Docker's network is outside the
tailnet. There are two separate remedies. A different network namespace with a
userspace tailscale sidecar gives the workload its own identity, which the ACL
can then scope. Dropping `100.64.0.0/10` from its egress gives it no identity
at all: it keeps the tailnet out of reach, but the ACL never sees it. Measure
either one with a TCP connect from the container itself.

**Tags**: `#tailscale` `#ai-009` `#acl`
