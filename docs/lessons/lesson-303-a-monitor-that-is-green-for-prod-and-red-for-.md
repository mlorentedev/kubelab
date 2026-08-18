---
id: lesson-303-a-monitor-that-is-green-for-prod-and-red-for-
type: lesson
status: active
created: "2026-08-09"
owner: manu
tags: [kubelab, lesson, dns, docker, tailscale, magicdns, split-dns, uptime-kuma, monitoring, false-positive, mon-001, gotcha]
---

# A monitor that is green for prod and red for staging is reporting on its own resolver, not on your infrastructure (MON-001)

**Context:** Every `*.staging.kubelab.live` monitor in Uptime Kuma read DOWN. Staging is on `ace1`, an on-demand homelab node, so the first available story — the homelab is powered off — fitted perfectly and was wrong. `toolkit infra headscale probe` passed end to end: `ace1` SSH, `hub->spoke :6443 (staging)`, the RPi4 subnet route, the intra-K3s spoke API. The infrastructure being monitored was entirely up.

**Problem:** The RPi3 host resolved `api.staging.kubelab.live` to `100.64.0.11` correctly, through the Headscale split-DNS route to the RPi4. The `uptime-kuma` container, on the same host, returned `ENOTFOUND`.

Docker had declined to inherit the host's MagicDNS resolver and substituted its own upstreams, which its generated resolv.conf records in a comment that is easy to read past:

```
nameserver 127.0.0.11
# ExtServers: [host(75.75.75.75) host(75.75.76.76) ...]
```

Those are the ISP's resolvers. Staging DNS is VPN-only and has no public record, so every staging FQDN failed — while prod monitors stayed green, because prod resolves publicly through Cloudflare. That asymmetry is the whole trap: a resolver defect that only affects names with no public record is *indistinguishable from a real outage of exactly those services*, and it points the investigation at the infrastructure instead of at the prober.

The repo already carried a gotcha about Docker not inheriting host DNS, written for the systemd-resolved `127.0.0.53` stub, prescribing `dns: [1.1.1.1, 8.8.8.8]`. Applying it here would have been a plausible-looking change that fixed nothing: those resolvers cannot see staging either.

**Solution:** Pin the container to MagicDNS (`100.100.100.100`) via the `docker_dns_servers` idiom the `headscale` role already established, keeping a public resolver as a second entry so prod monitors survive Tailscale being down on the node. The CLAUDE.md gotcha was rewritten to separate the two cases and name the `# ExtServers:` line as the way to tell them apart.

One near-miss is worth recording. The first attempt to verify the fix queried MagicDNS from inside the container with `dns.setServers(['100.100.100.100'])` followed by `dns.lookup()`, and returned `ENOTFOUND` — apparently proving the fix would not work. `dns.setServers()` governs `dns.resolve*()` only; `dns.lookup()` goes through `getaddrinfo` and ignores it entirely, so the test had re-measured the broken path. `dns.resolve4()` returned `100.64.0.11`. A verification that silently exercises the thing you are trying to bypass is worse than no verification, because it carries the authority of evidence.

**Rule:** When a prober reports a partition of its targets down, first ask what distinguishes the failing set from the passing set. If the discriminator is a property of *name resolution* — public record vs split-DNS, internal vs external zone — suspect the prober's resolver before the targets. Check reachability from inside the probing container, not from its host; the host resolving correctly is not evidence, and on a split-DNS mesh it is the single most misleading observation available. And treat a documented gotcha as scoped to the mechanism it was written for: the same symptom from a different cause can make the recorded fix precisely inverted.

**Tags:** `#dns` `#docker` `#tailscale` `#magicdns` `#split-dns` `#uptime-kuma` `#monitoring` `#false-positive` `#mon-001` `#gotcha`
