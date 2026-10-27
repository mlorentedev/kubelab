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

Current setup, since the K3s cutover ([lesson-173](../lessons/kubernetes/lesson-173-k3s-ingressroute-needed-for-vpn-kubelab-live-.md)): **K3s Traefik terminates TLS, speaks plain HTTP to Headscale, and a TLSOption keeps clients on HTTP/1.1.** Everything is in `infra/k8s/overlays/prod/headscale.yaml` and the `headscale` Ansible role:

- IngressRoute `headscale` matches `Host(vpn.kubelab.live)` on `websecure` and takes its certificate from the `letsencrypt` resolver (`tls.certResolver`), so the certificate is Traefik's and renews itself.
- The route forwards to Service `headscale:8080`, whose EndpointSlice is the VPS public IP. Headscale listens on plain HTTP there (`listen_addr: 0.0.0.0:8080`, no `tls_*` in `config.yaml.j2`) and publishes the port on the public address only.
- TLSOption `headscale-http11` offers only `http/1.1` (TLS 1.2 minimum), so a client that offers HTTP/2 still negotiates HTTP/1.1, which is where `Upgrade: tailscale-control-protocol` can be sent at all. traefik#12609 (still open) reports the Upgrade header being stripped when an HTTP/2 connection is involved. Check it with `openssl s_client -connect vpn.kubelab.live:443 -servername vpn.kubelab.live -alpn h2,http/1.1 </dev/null 2>&1 | grep "ALPN protocol"` (expect `http/1.1`).
- The repo records no measurement that isolates the TLSOption as the reason the handshake succeeds (see Superseded, option 1). Treat the pair, HTTP/1.1 ALPN plus K3s Traefik, as the known-good configuration, and register a client (`tailscale up --login-server=https://vpn.kubelab.live`) after changing either.
- certbot and nginx are not part of this path; the `headscale` role purges them from the VPS (OPS-047, #2701).

Superseded (do not reintroduce):

1. **TCP passthrough with SNI** (2026-02-26, until the K3s cutover). Traefik routed raw TCP by SNI hostname and TLS terminated inside Headscale from a certbot DNS-01 (Cloudflare) certificate. It skipped the HTTP/2 layer entirely, but once Headscale moved behind K3s Traefik nothing read what certbot produced: its certificates expired (mlorente.dev in June 2025, vpn.kubelab.live on 2026-05-28) while the VPN kept working, and its timer failed every 12 hours (OPS-047 removes it). Forcing HTTP/1.1 ALPN did not fix the handshake on Traefik v3.0.4 at the time, but that attempt ran with a tsnet older than Headscale v0.28's minimum, which fails the same way ([lesson-075](../lessons/networking-dns/lesson-075-2026-02-26-traefik-cannot-proxy-headscale-cus.md), [lesson-076](../lessons/networking-dns/lesson-076-2026-02-27-tsnet-version-must-meet-headscale-.md)).
2. **Native Headscale TLS**, an earlier version of this page called it current. Headscale bound 443 itself with its own certificate and no Traefik in front. It was never part of the repo's IaC (the role has never rendered `tls_*`), and it is not what runs.

## When this recurs

- Re-enabling Traefik HTTP/2 in front of Headscale (e.g., trying to unify cert management).
- Upgrading Traefik majors — check release notes for any change to upgrade-header handling.
- New Tailscale client/tsnet versions that change the control-protocol negotiation.

## Cross-refs

- [headscale-setup](../runbooks/headscale-setup.md) — main runbook: §1.3 (TLS) and §1.4 (route) carry the current path, "Last tested" the 2026-02-26 incident note.
- [adr-013-vpn-consolidation](../adr/adr-013-vpn-consolidation.md) — overall VPN strategy.
- [adr-010-headscale-over-tailscale-cloud](../adr/adr-010-headscale-over-tailscale-cloud.md) — why self-hosted Headscale at all.
