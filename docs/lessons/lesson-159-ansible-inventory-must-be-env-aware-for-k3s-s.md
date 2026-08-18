---
id: lesson-159-ansible-inventory-must-be-env-aware-for-k3s-s
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, ansible, k3s, inventory, environments]
---

# Ansible inventory must be env-aware for k3s_servers group

**Context:** Deploying K3s HelmChartConfig to prod VPS but Ansible targeted ace1 (staging server).

**Problem:** `common.yaml` defines ace1 as the K3s server (correct for staging). Prod needs VPS as the K3s server. The Ansible inventory for `k3s_servers` group was not environment-aware.

**Solution:** Override `k3s_servers` group membership in `prod.yaml` via `networking.vps.ansible_groups`. The Ansible playbook resolves the correct target node based on `ENV` variable.

**Rule:** Any Ansible group that varies by environment must have overrides in the env-specific values file (staging.yaml, prod.yaml). common.yaml holds the default (staging).
**Tags:** `#ansible` `#k3s` `#inventory` `#environments`
