---
id: lesson-193-security-posture-divergence-between-domains
type: lesson
status: active
created: "2026-03-25"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Security posture divergence between domains

**Problem**: Security audit revealed kubelab.live has zero security headers (no HSTS, no x-frame-options, etc.) while mlorente.dev has full coverage. Both go through the same VPS Traefik, but kubelab.live routes through Cloudflare proxy which strips/doesn't add headers. Also TLS 1.0/1.1 still enabled on Cloudflare (Grade B). Port 8080 (K3s Pattern C) exposed publicly.

**Root cause**: mlorente.dev IngressRoute has `secure-headers` middleware attached. kubelab.live prod IngressRoutes may be missing it, or Cloudflare proxy overrides origin headers. No CAA records on either domain.

**Rule**: After any new domain/service goes to prod, run SSL Labs + Shodan audit. Security headers must be verified end-to-end (origin → CDN → client), not just at origin. Cloudflare TLS settings (min version, HSTS, OCSP) are separate from Traefik config and need explicit Terraform management.

---
