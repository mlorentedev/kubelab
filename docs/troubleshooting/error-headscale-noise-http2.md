---
id: error-headscale-noise-http2
type: troubleshooting
status: active
created: "2026-05-18"
---

## Symptom

Tailscale clients fail to complete the Noise protocol handshake against `vpn.kubelab.live` when Headscale is fronted by Traefik in HTTP/2 reverse-proxy mode. Symptoms include:

- `tailscale up` hangs at `NoState` or returns `connection refused` during handshake.
- Headscale logs show truncated control-protocol exchanges.
- `tsnet` clients fail silently with `EOF` mid-handshake (see also: tsnet version-pinning, [headscale-setup](../runbooks/headscale-setup.md#tsnet-version-floor)).

## Root cause

Headscale's Noise transport uses a custom HTTP `Upgrade` token: `Upgrade: tailscale-control-protocol`. Traefik's HTTP/2 reverse-proxy only proxies the standard `Upgrade: websocket` token and strips other upgrade headers before forwarding. The result is that the TLS terminator forwards a plain HTTP request to Headscale, which then can't transition into Noise framing.

## Workaround / fix

Two options, both documented in [headscale-setup](../runbooks/headscale-setup.md):

1. **TCP passthrough with SNI** (used 2026-02-26 → 2026-03-XX). Traefik routes raw TCP based on SNI hostname; TLS termination happens inside Headscale via certbot DNS-01 (Cloudflare). Skips the HTTP/2 layer entirely.
2. **Native Headscale TLS** (current). Headscale binds 443 directly with its own cert, no Traefik front. Simpler but loses Traefik observability.

## When this recurs

- Re-enabling Traefik HTTP/2 in front of Headscale (e.g., trying to unify cert management).
- Upgrading Traefik majors — check release notes for any change to upgrade-header handling.
- New Tailscale client/tsnet versions that change the control-protocol negotiation.

## Cross-refs

- [headscale-setup](../runbooks/headscale-setup.md) — main runbook, line ~669 incident note (2026-02-26).
- [adr-013-vpn-consolidation](../adr/adr-013-vpn-consolidation.md) — overall VPN strategy.
- [adr-010-headscale-over-tailscale-cloud](../adr/adr-010-headscale-over-tailscale-cloud.md) — why self-hosted Headscale at all.
