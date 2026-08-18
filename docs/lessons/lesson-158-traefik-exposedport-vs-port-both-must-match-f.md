---
id: lesson-158-traefik-exposedport-vs-port-both-must-match-f
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, traefik, k3s, helm, networking, redirect]
---

# Traefik exposedPort vs port — both must match for HTTP→HTTPS redirect

**Context:** HTTP→HTTPS redirect stopped working after port swap to 80/443.

**Problem:** In HelmChartConfig, `port` sets the container port and `exposedPort` sets the Service port. The HTTP→HTTPS redirect middleware uses the container port. If `exposedPort=80` but `port=8080`, the redirect targets port 8080 instead of 80, producing broken redirect URLs.

**Solution:** Set both `port` and `exposedPort` to the same value (80 for web, 443 for websecure). The redirect then works correctly.

**Rule:** When configuring Traefik entrypoints in K3s HelmChartConfig, always set `port = exposedPort` unless you have a specific reason for port mapping. Mismatched values break redirects.
**Tags:** `#traefik` `#k3s` `#helm` `#networking` `#redirect`
