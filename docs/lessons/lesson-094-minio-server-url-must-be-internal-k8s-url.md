---
id: lesson-094-minio-server-url-must-be-internal-k8s-url
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# MINIO_SERVER_URL Must Be Internal K8s URL

**Context**: Deploying MinIO to K3s with OIDC.

**Problem**: If `MINIO_SERVER_URL` is set to the public HTTPS URL (`https://minio.staging.kubelab.live`), MinIO tries to connect to itself through the external URL, causing redirect loops and TLS issues inside the cluster.

**Solution**: Set `MINIO_SERVER_URL=http://minio:9000` (internal K8s service name). The public URL goes in `MINIO_BROWSER_REDIRECT_URL` for the console redirect.

**Rule**: Internal service-to-service communication MUST use K8s service names (`http://service:port`), NEVER public HTTPS URLs. Public URLs are only for browser redirects and external-facing configuration.

---
