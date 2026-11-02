---
id: lesson-626-a-site-network-can-answer-dns-for-any-address-including-the-authoritative-one
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, acme, dns, networking]
---

# A site network can answer DNS for any address, including the authoritative one

**Context**: Traefik issues certificates with ACME DNS-01 through Cloudflare. Before it asks Let's Encrypt to validate, lego checks that the challenge TXT record is visible on the zone's authoritative nameservers, by querying them directly over UDP 53. Staging (ace1) moved with the lab behind a new uplink (NET-005).

**Problem**: Every staging renewal timed out with `propagation: time limit exceeded ... vita.ns.cloudflare.com.:53 returned NXDOMAIN for _acme-challenge.<host>`, although the record had been created. The site answers every outbound UDP 53 query itself, whatever the destination: from rpi4 and from ace1, `dig +norec @192.0.2.1 example.com` (TEST-NET-1, no such host) answered NOERROR, and `vita.ns.cloudflare.com` answered `google.com` with Google's addresses and a falling TTL, which a Cloudflare authoritative server would refuse. TCP 53 got no answer at all. Nothing in the lab redirects port 53: rpi4's nat `PREROUTING` and `OUTPUT` jump to `DOCKER` only for local destinations. So lego's "authoritative" check read the site's cache, which held the NXDOMAIN from before the record existed.

**Solution**: The check is a local optimization; Let's Encrypt validates from its own network. Both environments now disable it and wait a fixed 60 s instead (`dnschallenge.propagation.disableChecks=true`, `propagation.delayBeforeChecks=60s`, `k3s_traefik_acme_propagation_checks: false`), asserted by `tests/test_traefik_offline_start.py`. #2699.

**Rule**: Asking a specific server a DNS question does not mean that server answers. Before trusting a resolution failure on a network you do not control, ask an address that cannot answer (`192.0.2.1`) and see whether something does. And keep a check that only optimizes something a third party verifies anyway from turning into a hard precondition.

**Tags**: `#acme` `#dns` `#site-network` `#issue-2699`
