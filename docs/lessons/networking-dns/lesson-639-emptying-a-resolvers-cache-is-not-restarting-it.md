---
id: lesson-639-emptying-a-resolvers-cache-is-not-restarting-it
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, pihole, coredns, rpi4, cache]
---

# Emptying a resolver's cache is not restarting it

**Context**: Lesson 560 made every Corefile change restart Pi-hole, because Pi-hole cached CoreDNS's old answers for up to an hour. Since ADR-075 that Pi-hole is the resolver the lab's LAN gets from DHCP (#2716).

**Problem**: The restart emptied the cache by stopping the resolver. Deploying #2715 restarted it, and a pull on ace1 failed with `lookup production.cloudfront.docker.com: Try again` in the same minute. ace1 fell back to its static secondary; a client without one has no fallback. The restart was chosen because CLAUDE.md said `pihole reloaddns` does not reload dnsmasq configs. That is true, but it is a statement about configuration and says nothing about the cache.

**Solution**: Measured on `pihole/pihole:2026.10.0` (FTL v6.8, the digest the RPi4 runs), with CoreDNS 1.12.1 serving a `hosts` record at TTL 3600:

- After the record moved and CoreDNS restarted, Pi-hole kept answering the old address from its cache.
- `pihole reloaddns` sends FTL a `HUP` (`/usr/local/bin/pihole`, `reloadDNS`). The next query returned the new address, and FTL kept its PID.
- With a query every 50 ms for 15 s, the flush lost 0 of 215 queries. `docker restart pihole` lost 10, about ten seconds without resolution.

The `coredns` role now restarts Pi-hole only when `pihole-forwarding.conf` changes. On a Corefile-only change it runs the flush after CoreDNS and Pi-hole both answer. `tests/test_coredns_pihole_cache.py` evaluates both `when` conditions and runs the flush the task declares against containers built from the role's own image defaults.

**Rule**: Before stopping a service to clear its state, check whether it has an operation that clears that state alone, and measure it on the version you deploy. A note that a reload "does not reload X" says nothing about whether it clears Y.

**Tags**: `#pihole` `#coredns` `#dns-007` `#pr-2716`
