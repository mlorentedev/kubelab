---
id: lesson-172-deploy-vps-must-be-idempotent-skip-docker-com
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# deploy-vps must be idempotent — skip Docker Compose Traefik when K3s is active

**Context:** Running `make deploy TARGET=vps ENV=prod` restarted Docker Compose Traefik, which stole ports 80/443 from K3s Traefik. This effectively reverted the K3s cutover.

**Problem:** deploy-vps.yml always ran traefik_vps role regardless of environment. No condition to detect K3s as active ingress.

**Solution:** Added `when: "'k3s_servers' not in group_names"` to traefik_vps and errors roles. In prod (VPS in k3s_servers group), these roles are skipped. In staging (VPS not in k3s_servers), they run normally.

**Rule:** Ansible playbooks must be environment-aware. Docker Compose services superseded by K3s must be conditional on the K3s deployment state.
**Tags:** `#ansible` `#traefik` `#k3s` `#idempotency` `#deploy`
