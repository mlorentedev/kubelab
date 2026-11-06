---
id: lesson-716-a-network-scoped-access-rule-behind-a-masquerading-load-balancer-matches-every-client
type: lesson
status: active
created: "2026-11-05"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, authelia, networking]
---

# A network-scoped access rule behind a masquerading load balancer matches every client

**Context**: SEC-036 (#2669) set out to split `networking.trusted_cidrs` into an egress deny list and a narrower Authelia trust list. The ticket assumed that only lab and LAN sources could match Authelia's `internal` network.

**Problem**: No client reaches Authelia with its own address. K3s's ServiceLB (klipper-lb) masquerades every connection (lesson-327), Traefik forwards the pod address it sees in `X-Forwarded-For`, and Authelia evaluates that address. Over 24h of prod Loki on 2026-11-05, every address Authelia logged was in `10.42.0.0/16`, including internet scanners probing `/.git/config`. CrowdSec saw no public address in the same window. So `internal` (`10.0.0.0/8`, ...) matched everyone, and prod's `vpn` (`100.64.0.0/10`) matched no one. The two `networks:` catch-alls read like "a login prompt from inside, deny from outside", but they gave the login prompt to everyone. Narrowing the list would have changed nothing.

**Solution**: Removed both catch-alls and every `networks` definition, gave the one host that relied on a catch-all (`traefik.staging.kubelab.live`) its own rule, and stopped the dev generator rendering `trusted_cidrs` as `internal`. `tests/test_authelia_access_rules.py` renders both overlays and fails if a host behind the `authelia` ForwardAuth has no explicit rule, or if any rule is scoped by network while #1067 is open.

**Rule**: Before writing any rule keyed on a client address (an Authelia `networks` entry, a Traefik `ipAllowList`, a CrowdSec allowlist, a per-IP rate limit), measure the address the deciding component actually logs for a request from a known outside source. A boundary is only real if that address is the client's own. Where it is not, write rules that do not depend on it, and add a test that keeps them out until the address is fixed.

**Tags**: `#authelia` `#klipper-lb` `#sec-036` `#1067`
