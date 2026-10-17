---
id: lesson-097-coredns-on-rpi4-is-completely-outside-k3s-and
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# CoreDNS on RPi4 Is Completely Outside K3s and Ansible Automation

**Context**: Added new services (gitea, n8n, minio) to the Corefile and needed to deploy changes to the RPi4 DNS gateway.

**Problem**: The CoreDNS deployment on RPi4 has no automation whatsoever. No Ansible role, no toolkit command, no CI/CD. The RPi4 is not in the K3s cluster — it's a standalone Docker Compose host. Changes to `edge/dns-gateway/Corefile` only take effect after manual SCP + container restart. This is a genuine automation gap, not a missing discovery.

**Solution**: Manual deployment: `scp edge/dns-gateway/Corefile manu@100.64.0.5:~/coredns/` then `ssh manu@100.64.0.5 "cd ~/coredns && docker compose -f compose.base.yml restart coredns"`. The runbook `dns-homelab.md` documents this procedure.

**Rule**: Always know the deployment mechanism for every component before referencing "apply changes" in any plan. The DNS gateway is a manual-deploy component — plan accordingly. Automated via `make deploy-dns` (SCP + restart). Future: consider Ansible role for `gateway_nodes`.

---
