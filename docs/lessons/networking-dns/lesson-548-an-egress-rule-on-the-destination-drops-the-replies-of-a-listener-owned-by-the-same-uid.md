---
id: lesson-548-an-egress-rule-on-the-destination-drops-the-replies-of-a-listener-owned-by-the-same-uid
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, nftables, conntrack, rootless, hermes, egress]
---

# An egress rule on the destination drops the replies of a listener owned by the same uid

**Context**: ace2 refuses the agent's Unix user the tailnet with an nftables
rule in the output hook, keyed on the uid (`meta skuid`) and conntrack's
original destination (lesson-525, lesson-527). #2161 measured that the same user
still reached the homelab LAN and every Docker bridge on the node (rpi4:80,
Beelink's and ace2's own sshd, Open WebUI's backend by container address), so
the private ranges had to be refused too.

**Problem**: the agent's user also *serves*. Hermes publishes its API on Open
WebUI's bridge gateway, `172.30.250.1:8642`, through rootlesskit's listener, a
process of that user in the host's namespace (lesson-542). Every answer it
sends to Open WebUI leaves through the output hook as that uid, and the
connection's original destination is `172.30.250.1`, inside `172.16.0.0/12`. A
rule on `skuid` plus `ct original ip daddr` alone refuses every reply, and Open
WebUI loses Hermes while the rule reads as correct.

**Solution**: refuse only connections the uid opens: `meta skuid <uid> ct state
new ct original ip daddr <range> reject`. A reply belongs to an established
connection and passes. Measured on ace2, 2026-10-10, after the rule: the agent's
user is refused all six probes (LAN, docker0, Open WebUI's and the bridge's
container addresses) and still opens `1.1.1.1:443`; the provision's "Reach the
Hermes API from Open WebUI's network" stays green; `changed=0` on the rerun.

**Rule**: before refusing a uid a range in the output hook, ask whether that
uid listens on an address inside the range. If it does, the rule needs `ct
state new`, and the provision must keep a probe of that listener from its
client, or the refusal of the replies will look like a dead service.

**Tags**: `#nftables` `#egress` `#pr-2161`
