---
id: lesson-052-yaml-duplicate-keys-silently-overwrite
type: lesson
status: active
created: "2026-02-14"
owner: manu
tags: [kubelab, lesson]
---

# YAML Duplicate Keys Silently Overwrite

**Context**: Adding gitea domain override to dev.yaml under `apps.services.core`.

**Problem**: Created a second `core:` block instead of adding to the existing one. YAML silently uses the last occurrence, wiping traefik/portainer/n8n overrides. Portainer started routing to `kubelab.live` instead of `kubelab.test`.

**Solution**: Always search for existing key before adding new entries. YAML does NOT merge duplicate keys.

**Rule**: When editing YAML overrides, verify with `python3 -c "import yaml; print(yaml.safe_load(open('file.yaml')))"` that keys aren't duplicated.
