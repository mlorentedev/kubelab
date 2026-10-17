---
id: lesson-076-2026-02-27-tsnet-version-must-meet-headscale-
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# 2026-02-27 — tsnet Version Must Meet Headscale minimum_version

**Context:** After fixing all Traefik routing issues (TCP passthrough, certbot TLS, DNS), ts-bridge still failed with identical `308 Permanent Redirect / reading response header: EOF` error. Native Tailscale clients worked fine.

**Problem:** Headscale v0.28.0 enforces `minimum_version=v1.74`. ts-bridge used `tailscale.com v1.60.0` — 14 minor versions below the minimum. The Noise handshake fails server-side due to version rejection, manifesting as EOF on the client.

**Diagnosis clues:**
- curl and native Tailscale clients (>= v1.74) worked through the same TCP passthrough
- Headscale logs showed: `Clients with a lower minimum version will be rejected minimum_version=v1.74`
- ts-bridge reported: `IPNVersion: 1.60.0-dev`

**Fix:** `go get tailscale.com@v1.80.0 && go mod tidy`. tsnet API surface (`tsnet.Server`, `Up()`, `Dial()`, `Close()`) is stable across v1.60→v1.80; no code changes needed.

**Rule:** When integrating with Headscale, check its `minimum_version` log entry and ensure the tsnet Go module exceeds it. Pin to minimum + 6 minor versions for safety. Add this check to the pre-release validation for any Headscale-compatible tool.

---
