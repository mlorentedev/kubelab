---
id: lesson-527-a-filter-on-daddr-misses-a-port-published-on-the-same-host
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, nftables, docker, nat, agents]
---

# An output filter on `daddr` misses a port that Docker publishes on the same host

**Context**: AI-009 PR 3b refuses the tailnet to the agent's user on ace2
(lesson-525). It is an nftables table of its own, with an output chain at
priority `filter` and the rule
`meta skuid <agent> ip daddr 100.64.0.0/10 reject`.

**Problem**: From the agent's gateway, the VPS, both K3s APIs, Gitea and
MagicDNS were refused, but ace2's own Open WebUI at `100.64.0.5:3080` still
connected. The system daemon publishes that port on ace2's tailnet address, so
Docker DNATs locally generated traffic to it in the nat `OUTPUT` chain. That
hook runs at priority -100, before any filter chain at priority 0. By the time
the rule ran, `daddr` held the container's bridge address, not `100.64.0.5`, and
nothing matched. The provision's probe passed because it only tried the VPS,
which no local DNAT rewrites.

**Solution**: Match the address the process asked for, which conntrack keeps
through the rewrite: `meta skuid <agent> ct original ip daddr 100.64.0.0/10`
(and `ct original ip6 daddr` for the ULA range). After the change, every tailnet
destination timed out from the gateway, `ace2:3080` included, and the VPS's
public `:443` still answered. A second provision probe now tries this node's own
published port, and `tests/test_agent_egress.py` fails on any rule without
`ct original`.

**Rule**: On a host that also runs Docker with published ports, an output
filter that judges the destination must use `ct original ip daddr`, or run
before nat (priority below -100). A plain `daddr` sees the address after the
DNAT. Probe the case you are excluding from the same host, not only from a
remote one, because a remote destination is never rewritten.

**Tags**: `#nftables` `#docker` `#ai-009` `#acl`
