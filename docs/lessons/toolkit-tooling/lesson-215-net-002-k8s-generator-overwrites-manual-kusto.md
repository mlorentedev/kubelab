---
id: lesson-215-net-002-k8s-generator-overwrites-manual-kusto
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# NET-002: K8s Generator Overwrites Manual kustomization.yaml — Prod Outage

**What happened:** `make deploy-k8s ENV=prod` runs `generator_k8s.py` which overwrites `infra/k8s/overlays/prod/kustomization.yaml` with a template that only includes 4 generated resources. The prod file had 7 additional manual resources (argocd.yaml, headscale.yaml, backup.yaml, patches.yaml, etc.). After deploy, those resources were silently dropped from the Kustomize overlay — IngressRoutes for headscale proxy, uptime-kuma, traefik-dashboard disappeared. Combined with CrowdSec bouncer plugin loss, this caused a full prod outage.

**Root cause:** Mixing generated and manual files in the same directory without separation. The generator treats kustomization.yaml as generated, but operators add manual resources to it over time. Each deploy silently destroys manual additions.

**Fix (ADR-027 Phase 2):** Move generated files to `overlays/{env}/generated/` subdir. Make kustomization.yaml a manual committed file referencing `generated/*.yaml`. Generator stops generating kustomization.yaml. Gitignore `overlays/*/generated/`.

**Pattern:** Never mix generated and hand-maintained files in the same directory. Generated files go in `generated/` (gitignored). Entry points (kustomization.yaml) are always manual and committed.
