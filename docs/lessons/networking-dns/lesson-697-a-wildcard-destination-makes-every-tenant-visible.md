---
id: lesson-697-a-wildcard-destination-makes-every-tenant-visible
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, headscale, acl, tailscale, multi-tenant]
---

# A wildcard destination makes every tenant visible, because a grant in either direction shows both peers

**Context**: Another organisation's lab was to enrol in the shared Headscale as its own segment (VPN-ACL-014, #2830). The deployed policy's rule 1 was the permissive-first baseline of ADR-041 §4(b): the private users reached `*:*`.

**Problem**: That wildcard made isolation impossible to express. A tenant node registered under any identity was either a source of rule 1 or one of its destinations, and Headscale puts both peers in each other's netmap when a grant exists in either direction. So the tenant would have seen every private peer even with no rule naming it, and Headscale's policy is allow-only, so no later rule can subtract a node from a `*`. Measured on 2026-10-30 through the read-only audit identity (SEC-037): the live policy equalled the rendered template, wildcard included.

**Solution**: Rule 1 names its destinations: the private users, `agents@`, `tag:hermes` and `lan-rpi4`, each on every port, which for every node and route held that day equals the old wildcard. A segment is data from SOPS that grants only `clients_tag -> hosts_tag:<ports>`. The deploy stops if a node Headscale holds would fall outside rule 1 and every segment. Rollback never restores a `.prev` with a wildcard while segments are declared, and the first-activation fallback is the segment-free policy, not an allow-all. Read back after the deploy: three rules, no wildcard, 14 nodes unchanged (#2832, #2853, #2872).

**Rule**: In a Tailscale-model ACL, visibility is symmetric and grants are only additive. Before admitting anyone who must not see the rest, replace every `*` destination with an enumerated list, and make the deploy refuse a node the list does not account for, so the enumeration cannot silently fall behind the inventory.

**Tags**: `#headscale` `#acl` `#issue-2830` `#pr-2832`
