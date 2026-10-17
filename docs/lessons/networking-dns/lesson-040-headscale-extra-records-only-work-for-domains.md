---
id: lesson-040-headscale-extra-records-only-work-for-domains
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale extra_records only work for domains under its zones

**Context**: Trying to add `staging.mlorente.dev` as Headscale extra_record for VPN-only DNS resolution.

**Problem**: `extra_records` in Headscale only serves records for domains under its configured zones (`kubelab.live`, `kubelab.vpn`). External domains like `mlorente.dev` are delegated to global nameservers (1.1.1.1) — the extra_record is ignored.

**Solution**: Use Cloudflare DNS A record pointing to Tailscale IP (100.64.0.4). Non-routable from internet, works for VPN clients. Managed via Terraform.

**Rule**: For VPN-only staging domains on external zones, use Cloudflare DNS (not Headscale extra_records). Headscale extra_records only for `*.kubelab.live` bare-metal services.
