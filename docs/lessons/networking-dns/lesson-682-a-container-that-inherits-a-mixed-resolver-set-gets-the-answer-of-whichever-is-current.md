---
id: lesson-682-a-container-that-inherits-a-mixed-resolver-set-gets-the-answer-of-whichever-is-current
type: lesson
status: active
created: "2026-10-31"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, gitea, docker, systemd-resolved, coredns, webhook]
---

# A container that inherits a mixed resolver set gets the answer of whichever server is current

**Context**: Gitea on the Beelink delivers webhooks to `pr-agent.kubelab.live`. Gitea refuses private and CGNAT targets (`ALLOWED_HOST_LIST=external`, the default), and the hook was designed on the public-IP path that already worked for other hooks.

**Problem**: Deliveries were denied intermittently with `deny pr-agent.kubelab.live(100.64.0.2:443)`, with no config change in between. The container's `/etc/resolv.conf` read `ExtServers: [host(127.0.0.53)]`, so the host resolver *was* inherited correctly. Neither case of the Docker-DNS gotcha in CLAUDE.md applied (a stub that Docker replaces, or MagicDNS falling through to DHCP servers). The host's own set was the problem: systemd-resolved held `8.8.8.8 1.1.1.1 172.16.1.1` on one link and answers from one current server, which it changes only on failure. `172.16.1.1` is the LAN gateway, whose prod zone deliberately maps every public name to its tailnet address (lesson-559, #2213). Measured with the same config: on 2026-10-22 the current server was the gateway and both `pr-agent` and `n8n` resolved to 100.64.0.2 inside the container; on 2026-10-31 it was `8.8.8.8` and both resolved to 162.55.57.175, with three deliveries answering 200.

**Solution**: The `gitea` service pins `dns:` to public resolvers (`gitea_dns_servers` in `beelink_services`), so the webhook filter always sees the public address. `ALLOWED_HOST_LIST` stays at its default, because widening it would increase the SSRF surface. MagicDNS was rejected, because with `override_local_dns: false` it forwards non-split names to the same host resolvers. `tests/test_gitea_webhook_resolver.py` renders the compose template and fails if the service has no pin or if a pinned resolver is private, LAN or tailnet. The test's first red was a missing Jinja filter, not the missing pin, so a red result is only evidence after you read its reason.

**Rule**: A resolver list that mixes servers which answer the same name differently is not redundancy: it is a coin flip that changes only on failure. A client that cares which answer it gets must pin resolvers that agree. When a symptom comes and goes with no deploy in between, check which server `resolvectl status` reports as current before suspecting the config.

**Tags**: `#gitea` `#systemd-resolved` `#webhook` `#issue-2886`
