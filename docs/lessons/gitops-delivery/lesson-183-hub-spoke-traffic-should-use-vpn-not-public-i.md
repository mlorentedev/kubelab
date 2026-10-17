---
id: lesson-183-hub-spoke-traffic-should-use-vpn-not-public-i
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Hub↔spoke traffic should use VPN, not public IPs

**Context**: Deciding whether Argo CD hub should connect to prod spoke via public IP or Tailscale VPN.

**Problem**: CLAUDE.md says "VPS must use public_ip" but that rule is for Ansible/bootstrap (circular dependency with Headscale). Applying it to Argo CD would expose K8s API traffic on the public internet unnecessarily.

**Solution**: Both spokes use Tailscale IPs in the hub cluster Secret. All Argo CD traffic stays on WireGuard mesh. The bootstrap rule only applies to tools that need to reach VPS when Tailscale is down (Ansible, user kubeconfig).

**Rule**: Distinguish bootstrap tools (Ansible, SSH — use public IP) from runtime services (Argo CD, monitoring — use VPN). Runtime services should always prefer VPN for security and consistency.
