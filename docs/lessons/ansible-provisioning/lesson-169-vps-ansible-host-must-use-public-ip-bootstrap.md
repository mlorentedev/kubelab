---
id: lesson-169-vps-ansible-host-must-use-public-ip-bootstrap
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# VPS ansible_host must use public IP — bootstrap circular dependency

**Context:** Ansible inventory used Tailscale IP (100.64.0.2) as `ansible_host` for VPS. But VPS hosts Headscale (the VPN control plane). When Tailscale was down, we couldn't SSH to VPS via Ansible to fix Headscale — circular dependency.

**Problem:** `generator_ansible.py` always used `tailscale_ip` for VPS. VPS is the only node that MUST be reachable without VPN.

**Solution:** Changed generator to use `public_ip` for VPS: `vps.get("public_ip") or vps.get("tailscale_ip")`. Also updated kubeconfig to use public IP (162.55.57.175:6443).

**Rule:** Bootstrap infrastructure (Headscale host) must NEVER depend on the service it bootstraps (Tailscale) for management access.
**Tags:** `#ansible` `#vps` `#headscale` `#bootstrap` `#networking`
