---
id: lesson-218-web-crashloopbackoff-three-root-causes-behind
type: lesson
status: active
created: "2026-03-27"
owner: manu
tags: [kubelab, lesson, k8s, kustomize, nginx, traefik, debugging]
---

# Web CrashLoopBackOff: three root causes behind one symptom

**Context:** Deploying web service to prod after merging PR #136 (BUG-WEB-001 nginx PID fix). Pod kept crashing despite Dockerfile fix.
**Problem:** Three independent issues masked as one CrashLoopBackOff: (1) Image tag `dev` in prod — base kustomization.yaml had no image pin for custom apps web/api, only errors. (2) Container port 4321 (Astro dev server) instead of 8080 (nginx) — common.yaml default_port is for dev, staging/prod need override. (3) Missing error-pages middleware on generated IngressRoutes — users saw raw Traefik "no available server" instead of custom error page.
**Solution:** Pin custom app images in base/kustomization.yaml (web:1.0.1, api:1.0.0, errors:1.1.1). Override default_port: 8080 in staging.yaml and prod.yaml. Add error-pages as default middleware in K8s generator _build_middlewares(). All three fixes shipped in PRs #138 and #139.
**Tags:** `#k8s` `#kustomize` `#nginx` `#traefik` `#debugging`
