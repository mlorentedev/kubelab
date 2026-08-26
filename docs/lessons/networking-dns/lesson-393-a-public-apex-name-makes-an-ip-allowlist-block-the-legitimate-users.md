---
id: lesson-393-a-public-apex-name-makes-an-ip-allowlist-block-the-legitimate-users
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, traefik, split-dns, tailscale, gitea, issue-1389]
---

# An IP allow-list restricts by the address Traefik SEES, and a name in the apex zone resolves publicly even from inside the VPN

**Context**: Deciding whether `gitea.kubelab.live` should stay publicly reachable (#1389 AC3). The obvious answer — apply the `vpn-whitelist` middleware, which already exists and which Loki's route already carries — was written into the ticket as a recommendation.

**Problem**: It would have blocked every legitimate client, including the machines it was meant to serve.

`vpn-whitelist` is an `ipAllowList` over `100.64.0.0/10` (Tailscale), loopback, the K3s pod and service CIDRs, and `172.16.0.0/12` (homelab LAN). The reasoning was "everyone who needs Gitea is on the tailnet, so those ranges cover them". The reasoning skipped a step:

```
$ getent hosts gitea.kubelab.live
162.55.57.175   gitea.kubelab.live
```

**Headscale's split DNS is deliberately narrowed to `staging.kubelab.live`** — broadening it would make prod unresolvable whenever the RPi4 is down. So a name in the *apex* zone resolves through public DNS even from a machine on the tailnet, the traffic leaves over the open internet, and Traefik sees the client's **ISP address**, which matches none of those ranges. Being on the VPN does not put you on the VPN *as far as the edge is concerned*.

The `172.16.0.0/12` entry is what makes the mistake easy: it works in **staging**, where Traefik runs on ace1 and clients share the LAN. In **prod** Traefik is on the VPS and nothing arrives from the homelab range, so the same middleware means different things in the two environments.

**Solution**: Restrict by **where the name points**, not by where the packet claims to come from — the OPS-022 pattern already used for Pi-hole. `infra/terraform/dns/services.json` takes an optional `target`, resolved against a node-to-Tailscale-IP map, so the A record can name the VPS's mesh address. Verified before deciding: `curl --resolve gitea.kubelab.live:443:100.64.0.2` returns 200 — Traefik already listens there, and the certificate is valid because the resolver uses a DNS-01 challenge and never needed inbound HTTP.

**Rule**: Before adding an IP allow-list, resolve the hostname from a client you intend to allow and confirm the address the edge will observe. Split DNS scoped to a subdomain does not cover the apex, so "we are all on the VPN" is a statement about the clients and not about the connection. Prefer the DNS repoint where the goal is unreachability: **public resolution is not public reachability**, it survives the resolver being down, and it cannot be defeated by a proxy rewriting the source address. Do not describe either as hiding the name — Certificate Transparency published it when the certificate was issued.

**Tags**: `#traefik` `#split-dns` `#tailscale` `#ip-allowlist` `#issue-1389`
