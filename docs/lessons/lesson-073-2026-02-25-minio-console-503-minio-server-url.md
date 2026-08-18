---
id: lesson-073-2026-02-25-minio-console-503-minio-server-url
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-02-25 — MinIO console 503: MINIO_SERVER_URL must be internal in dev

**Problem:** MinIO console login returns 503 / "unable to login due to network error" in Docker Compose dev.

**Root cause:** `MINIO_SERVER_URL=https://minio.kubelab.test` causes the embedded console (port 9001) to call the MinIO API at that public URL from inside the container. Port 443 (Traefik) only exists on the host — it is not reachable from inside Docker networks.

**Fix:** Override `MINIO_SERVER_URL` in `compose.dev.yml`:
```yaml
MINIO_SERVER_URL: "http://localhost:9000"      # internal — console→API call
MINIO_BROWSER_REDIRECT_URL: "https://console.minio.kubelab.test"  # external — browser redirect
```

**Rule:** Any service that embeds an admin console which calls its own API internally must use an internal URL for `*_SERVER_URL`, not the public HTTPS reverse-proxy URL.

---
