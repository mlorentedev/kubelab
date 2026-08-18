---
id: lesson-127-ansible-role-variables-dead-code-from-playboo
type: lesson
status: active
created: "2026-03-17"
owner: manu
tags: [kubelab, lesson, ansible, tailscale, code-review]
---

# Ansible role variables: dead code from playbook-side flags

**Context:** ADR-023 Phase 1 provisioning review — auditing tailscale role usage in provisioning playbooks
**Problem:** Both provisioning playbooks passed `tailscale_extra_flags: "--accept-routes"` to the tailscale role, but the role never uses that variable. The role has its own `tailscale_accept_routes` variable (default: false). Result: nodes would silently NOT accept routes from other VPN peers.
**Solution:** Always verify role defaults/main.yml to confirm which variables the role actually consumes before passing vars from playbooks. Fix: replace `tailscale_extra_flags` with `tailscale_accept_routes: true`. Prevention: pre-provisioning review of role interface (defaults + tasks) against playbook vars.
**Tags:** `#ansible` `#tailscale` `#code-review`
