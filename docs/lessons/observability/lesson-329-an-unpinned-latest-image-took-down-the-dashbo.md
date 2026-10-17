---
id: lesson-329-an-unpinned-latest-image-took-down-the-dashbo
type: lesson
status: active
created: "2026-08-14"
owner: manu
category: observability
tags: [kubelab, observability]
---

# An unpinned `:latest` image took down the dashboard the same day upstream shipped a major version

**Context:** SEC-004's rate-limit values need a real request-rate measurement, so before writing any Middleware, the plan was to reload the Homepage cockpit in staging and read the burst off Traefik's access log — the same diagnostic pattern already used earlier in this session. The page came back `503` instead.

**Problem:** both Homepage pods were crash-looping. `kubectl describe` showed `Readiness probe failed: HTTP probe failed with statuscode: 400`; the pod's own logs explained why: `Host validation failed for: 10.42.0.99:3000. Hint: Set the HOMEPAGE_ALLOWED_HOSTS environment variable to allow requests from this host / port.` kubelet's `httpGet` probes hit the pod's own IP directly — `10.42.0.99:3000` — but Homepage (a Next.js app) validates the incoming `Host` header against `HOMEPAGE_ALLOWED_HOSTS`, which only ever listed the two public domains. A probe request's `Host` header is whatever the destination IP:port is, so it was never going to match, and every probe got HTTP 400 → CrashLoopBackOff → the whole dashboard down.

The manifest pins nothing: `image: ghcr.io/gethomepage/homepage:latest`. Checking prod's *running* pod against upstream's release list explained the timing precisely — prod's pod was 18h old (started well before today), and `gethomepage/homepage` shipped `v2.0.0` (a new Next.js major, plus a new built-in auth gate) hours before staging's pod restarted and pulled it fresh. Every other third-party image in this repo (n8n, authelia, loki, minio, crowdsec, redis...) is pinned through the `apps.services.*.image` SSOT in `common.yaml` and synced into `kustomization.yaml`'s `images:` transformer by `sync_k8s_images.py` — Homepage was the one service that had never been brought into that pattern, left on a floating tag directly in the base manifest.

**Solution:** two independent fixes, both required:
1. Both probes now send an explicit `Host` header that's already in `HOMEPAGE_ALLOWED_HOSTS` (`httpHeaders: [{name: Host, value: home.staging.kubelab.live}]`) — makes the probe's request match the allowlist regardless of which pod IP it landed on.
2. Brought Homepage's image into the existing pinning SSOT: `apps.services.observability.homepage.image: ghcr.io/gethomepage/homepage:v1.13.2` in `common.yaml` (the last release before the `v2.0.0` jump — matches prod's empirically-known-good state, and avoids adopting the new unconfigured auth gate mid-incident), added to `sync_k8s_images.py`'s `IMAGE_SOURCES`, regenerated `kustomization.yaml` via `make sync-k8s-images`.

Fix 1 alone would have restored the dashboard on `v2.0.0` — but that version's behavior (new auth gate, whatever else the major bump changed) was never evaluated, so shipping it by accident on the next pod restart was still live risk. Fix 2 makes the whole incident non-recurring until a version bump is deliberate.

**Rule:**
- **`:latest` is not a version, it's a promise that the next pod restart might run different code than the last one** — a node drain, an OOM kill, or a routine rollout can all trigger a fresh pull. If every other image in the repo is pinned through one SSOT and one is not, that's the one that will break first and hardest, because nothing will have exercised the new version before it lands.
- **A Kubernetes `httpGet` probe sends whatever Host the destination IP:port implies — never the app's real hostname.** Any app that validates the `Host` header (Next.js's `allowedHosts`, and increasingly common elsewhere as a DNS-rebinding defense) will reject kubelet's own health checks unless the probe explicitly overrides it with `httpHeaders: [{name: Host, value: ...}]`. Look for this class of failure whenever a probe starts failing right after an app's base image moves, with no change to the app's own manifest.
- **When a live pod is healthy and a sibling pod of the same Deployment is crash-looping, diff what's actually different, not just what changed in git** — here, nothing in the repo changed; the two pods differed only in which real-world instant they last pulled `:latest`.

**Tags:** `#kubernetes` `#homepage` `#image-pinning` `#liveness-probe` `#next.js` `#sec-004` `#gotcha`

---
