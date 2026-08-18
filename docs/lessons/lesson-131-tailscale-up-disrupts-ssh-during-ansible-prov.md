---
id: lesson-131-tailscale-up-disrupts-ssh-during-ansible-prov
type: lesson
status: active
created: "2026-03-17"
owner: manu
tags: [kubelab, lesson, tailscale, ansible, ssh, async, provisioning]
---

# Tailscale up disrupts SSH during Ansible provisioning

**Context:** ADR-023 Phase 1 — running tailscale up via Ansible on fresh node
**Problem:** tailscale up modifies routing table immediately, killing SSH connection. Synchronous Ansible command task hangs forever waiting for response. Node becomes unreachable via LAN. --timeout=30s flag didn't help because network broke before timeout could trigger.
**Solution:** Use async Ansible task: async: 60 + poll: 0, then async_status with retries. This launches tailscale up in background so Ansible doesn't depend on SSH surviving. Still may fail retries if LAN routing is broken (see subnet route issue). Real fix: ensure LAN fallback works independently of Tailscale routing.
**Tags:** `#tailscale` `#ansible` `#ssh` `#async` `#provisioning`
