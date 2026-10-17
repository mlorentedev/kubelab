---
id: lesson-168-headscale-override-local-dns-must-be-false
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Headscale override_local_dns must be false

**Context:** Headscale had `override_local_dns: true` in DNS config. This made Tailscale override all clients' system DNS with `100.100.100.100` (MagicDNS proxy). When Headscale/Tailscale was unreachable (e.g., after K3s cutover broke TLS), ALL DNS resolution failed on the workstation — not just VPN domains.

**Problem:** `override_local_dns: true` couples ALL DNS resolution to VPN control plane availability. Single point of failure.

**Solution:** Changed to `override_local_dns: false` in `infra/ansible/roles/headscale/templates/config.yaml.j2`. Split DNS still works for specific domains (staging.kubelab.live, kubelab.vpn) but system DNS stays independent.

**Rule:** VPN DNS should be additive (split DNS for specific zones), never override global system DNS.
**Tags:** `#headscale` `#dns` `#tailscale` `#vpn` `#reliability`
