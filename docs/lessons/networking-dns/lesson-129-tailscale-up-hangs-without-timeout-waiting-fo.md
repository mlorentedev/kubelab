---
id: lesson-129-tailscale-up-hangs-without-timeout-waiting-fo
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# tailscale up hangs without --timeout waiting for DERP mesh

**Context:** ADR-023 Phase 1 provisioning — ace2 first Tailscale registration via Ansible
**Problem:** tailscale up --authkey registered the node in Headscale successfully (confirmed in logs: node.id=15 connected), but the command hung indefinitely waiting for full DERP mesh connectivity. This blocked the Ansible playbook and made ace2 unreachable via SSH. Had to power cycle.
**Solution:** Add --timeout=30s to the tailscale up command and timeout: 60 to the Ansible task. Registration completes fast; it's the mesh handshake that can hang. Also: /ts2021 returns 500 to curl (no WebSocket Upgrade header) — this is expected, not a real error. Smart plug didn't reliably power-cycle the MiniPC (BIOS auto-power-on needs hard power cut).
**Tags:** `#tailscale` `#headscale` `#ansible` `#provisioning` `#debugging`
