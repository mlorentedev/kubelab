---
id: lesson-118-traefik-certresolver-name-vs-acme-dns-provide
type: lesson
status: active
created: "2026-03-15"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Traefik certResolver name vs ACME DNS provider are different concepts

**Context:** Templating Traefik static config for VPS — entrypoint TLS certResolver
**Problem:** Used dns_provider variable ('cloudflare') as the certResolver name in entrypoint config. Traefik errored 'Router uses a nonexistent certificate resolver' because the resolver is NAMED 'letsencrypt' in certificatesResolvers block, while 'cloudflare' is the DNS challenge provider within that resolver.
**Solution:** Hardcode 'letsencrypt' as the certResolver name in entrypoint config. The dns_provider variable ('cloudflare') is only used inside the resolver's dnsChallenge.provider field. certResolver name ≠ DNS provider name.
**Tags:** `#traefik` `#acme` `#tls` `#ansible`
