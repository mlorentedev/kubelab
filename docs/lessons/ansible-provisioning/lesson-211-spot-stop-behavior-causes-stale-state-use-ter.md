---
id: lesson-211-spot-stop-behavior-causes-stale-state-use-ter
type: lesson
status: active
created: "2026-03-26"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Spot `stop` behavior causes stale state — use `terminate` for cattle

**Context**: aws1 Spot instance with `instance_interruption_behavior = "stop"`.

**Problem**: When AWS reclaims and restarts a stopped Spot instance: new public IP, SSH daemon hangs (reverse DNS timeout), Tailscale tunnel broken (stale WireGuard context). Instance appears "running" but is completely inaccessible.

**Solution**: For stateless workloads (Argo CD hub), use `terminate` + ASG(1,1) instead of `stop`. Cloud-init rebuilds from scratch — no stale state. Added `UseDNS no` to sshd_config in cloud-init to prevent SSH hangs. Phase 2: migrate to ASG with auto-replacement.

**Rule**: If the architecture is stateless (reconstructable from Git/IaC), the infrastructure must match — destroy and recreate, don't preserve and resume. "Cattle not pets" applies to the interruption behavior, not just the deployment model.
