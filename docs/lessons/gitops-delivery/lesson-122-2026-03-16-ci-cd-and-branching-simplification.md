---
id: lesson-122-2026-03-16-ci-cd-and-branching-simplification
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# 2026-03-16: CI/CD and Branching Simplification

**Lesson: release-please replaces custom semantic-version logic**
- **Problem**: Custom versioning with `paulhatch/semantic-version` + baseline tags + RC calculation produced bugs (0.0.0-rc.0, missing baseline tags, fragile `change_path` per app)
- **Solution**: Adopted `googleapis/release-please-action` with manifest mode for monorepo. Config-driven (`release-please-config.json`), zero custom logic. Creates Release PRs on master push, auto-generates changelogs and tags.
- **Impact**: Removed ~150 lines of custom CI logic. Eliminated baseline tag management, semantic-version action, GitOps update job, and manual tag creation.

**Lesson: trunk-based development > gitflow for single developer**
- **Problem**: `develop` branch added merge ceremony without value — extra merge step, merge conflicts, CI duplication, no real review gate for solo dev
- **Solution**: Eliminated `develop`. Master is the only permanent branch. Feature branches squash-merge directly to master. Environment separation via values files, not branches.
- **Impact**: Simpler CI (one target branch), cleaner git history (squash merge), GitOps-ready (ArgoCD works from single branch + values)

**Lesson: HelmChartConfig must include ALL Traefik config, not just ports**
- **Problem**: Ansible k3s_server role deployed a HelmChartConfig with only port customization, overwriting the existing one that had ACME certResolver + HTTPS redirect + Cloudflare token. Result: staging TLS certificates broke.
- **Root cause**: K3s only supports one HelmChartConfig per chart — deploying a new one replaces the entire config, not just the changed fields.
- **Fix**: Template includes ACME config conditionally (`k3s_traefik_acme_enabled`). All Traefik config in one template.
- **Rule**: When managing K3s HelmChartConfig via Ansible, the template MUST be the complete desired state. There is no merge — it's a full replace.

**Lesson: Pattern C ports (8080/8443) belong in prod.yaml, not common.yaml**
- **Problem**: Setting alternate Traefik ports in common.yaml applied them to ALL environments including staging, breaking staging routing.
- **Fix**: common.yaml has standard ports (80/443). prod.yaml overrides to 8080/8443 for Pattern C (ADR-015 side-by-side validation).
- **Rule**: Environment-specific overrides go in env files. common.yaml = safe defaults that work everywhere.

**Lesson: Ansible role defaults should be empty for SSOT-sourced values**
- **Problem**: Roles had hardcoded defaults (e.g., `headscale_domain: "vpn.example.com"`, `traefik_image: "traefik:v3.6"`) that masked SSOT values and could cause silent failures if playbook vars weren't passed.
- **Fix**: Changed SSOT-dependent defaults to empty strings (`""`). Roles now fail explicitly if playbook doesn't provide values.
- **Rule**: Role defaults should be either empty (forcing playbook to provide) or safe generic values (timeouts, retry counts). Never environment-specific values.
