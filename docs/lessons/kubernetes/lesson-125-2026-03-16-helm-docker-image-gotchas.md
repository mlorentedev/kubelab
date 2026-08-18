---
id: lesson-125-2026-03-16-helm-docker-image-gotchas
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# 2026-03-16: Helm + Docker Image Gotchas

**Lesson: Mutable tags (:dev) require imagePullPolicy Always + pod restart**
- K8s default `IfNotPresent` caches the image on the node. Even with `Always`, Helm won't restart pods if the tag doesn't change.
- Fix: Use immutable tags (1.0.0) in production. For dev, set `pullPolicy: Always` and accept that `rollout restart` may be needed.

**Lesson: Traefik error middleware serves HTML but assets resolve against original domain**
- Error page HTML from errors service references `/errors/404.webp`, but the browser requests it from the original domain (e.g., staging.mlorente.dev), which doesn't have the image.
- Fix: Base64 inline images in error pages. Zero external dependencies.

**Lesson: CI push + pull_request triggers cause duplicate runs**
- With both `push: branches` and `pull_request: branches` in ci.yml, every push to a branch with an open PR triggers TWO CI runs.
- Fix: Use only `pull_request` trigger. Branch protection ensures PRs are required anyway.
