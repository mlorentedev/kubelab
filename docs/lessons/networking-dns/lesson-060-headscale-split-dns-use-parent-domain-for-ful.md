---
id: lesson-060-headscale-split-dns-use-parent-domain-for-ful
type: lesson
status: active
created: "2026-02-21"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale Split DNS: Use Parent Domain for Full Coverage

**Context**: CoreDNS resolved `*.staging.kubelab.live` but not `status.kubelab.live` (bare-metal).

**Problem**: Headscale split DNS was configured only for `staging.kubelab.live`. Bare-metal subdomains (`status.kubelab.live`, `ollama.kubelab.live`) didn't go through the internal DNS chain — they went directly to Cloudflare (which doesn't have those records) and returned NXDOMAIN.

**Solution**: Change split DNS from `staging.kubelab.live` → `kubelab.live` in Headscale config. This covers ALL internal subdomains. CoreDNS uses zone precedence: `staging.kubelab.live` (more specific) wins over `kubelab.live` for staging queries.

**Rule**: Configure split DNS on the parent domain (`kubelab.live`), not on specific subdomains. This way any new internal subdomain works automatically without touching Headscale.

---
