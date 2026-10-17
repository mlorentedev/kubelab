---
id: lesson-150-prod-web-container-port-8080-nginx-not-4321-a
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: apps-web
tags: [kubelab, apps-web]
---

# Prod web container port: 8080 (Nginx) not 4321 (Astro dev)

**Context:** Prod K3s web deployment returning 502 Bad Gateway.

**Problem:** common.yaml `default_port: 4321` is the Astro dev server port (used in Docker Compose for local development). The production Docker image runs Nginx on port 8080. K8s Service targetPort pointed to 4321 — no process listening there.

**Solution:** Always check the actual containerPort in the Dockerfile/image, not the dev config. K8s containerPort = 8080 (Nginx). The `default_port` in common.yaml is for Docker Compose dev only.

**Rule:** `default_port` in common.yaml = Docker Compose dev port. K8s containerPort = what the production image actually serves on. These are often different (dev server vs production server). Always verify against the Dockerfile.
**Tags:** `#k8s` `#ports` `#docker` `#debugging`
