---
id: "lesson-560-a-green-dns-deploy-is-not-what-clients-resolve-until-the-cache-in-front-expires"
type: lesson
status: active
title: "A green DNS deploy is not what clients resolve until the cache in front expires"
created: "2026-10-11"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, coredns, pihole, cache]
---

# A green DNS deploy is not what clients resolve until the cache in front expires

**Context**: #2213 moved `status.kubelab.live` from rpi3 to the VPS in rpi4's CoreDNS prod zone. `make deploy TARGET=dns ENV=prod` reported `changed=2`, then `changed=0`.

**Problem**: ace2 still resolved the old address. CoreDNS answered `100.64.0.2` with TTL 3600, and Pi-hole, which clients actually ask, answered `100.64.0.6` with 710s left. The role restarted CoreDNS on a Corefile change and Pi-hole only on a change to its own forwarding config, so every record change took up to the `hosts` plugin's TTL (an hour) to reach anyone.

**Solution**: The role restarts Pi-hole on a Corefile change as well, after CoreDNS. The role's own `Wait for CoreDNS` and `Wait for Pi-hole to resolve through CoreDNS` tasks prove DNS answers again at deploy time. `tests/test_coredns_pihole_cache.py` only guards the task wiring (the `when`, the `register` and the order); it resolves nothing.

Measured after the cache expired, on 2026-10-11 at 03:56 UTC: Pi-hole answered `100.64.0.2`, yet ace2's first `getent hosts status.kubelab.live` still printed `100.64.0.6`, and the `curl` right after it reached `100.64.0.2`. A client's own stub (systemd-resolved) is one more cache, and it holds its entry for the TTL it was given.

**Rule**: When a resolver sits behind a cache, a config change is live when the cache has dropped the old answer, not when the backend has the new one. The deploy that changes the record must also empty the cache in front. Verify from a client (`getent hosts <name>` on the node that failed), never by asking the backend or even Pi-hole directly: each layer between them is a cache of its own.

**Tags**: `#dns` `#pihole` `#coredns` `#issue-2213`
