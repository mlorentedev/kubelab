---
id: lesson-220-aws1-t4g-micro-disk-pressure-blocks-all-pod-s
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# aws1 t4g.micro disk-pressure blocks all pod scheduling

**Context:** Helm upgrade for Argo CD failed repeatedly with timeout. Pods stuck in Pending/ContainerCreating.
**Problem:** aws1 (6.8G disk) hit 84% usage → kubelet applied disk-pressure taint → NoSchedule on all new pods. Root cause: accumulated apt lists (247MB), apt cache (167MB), journal logs (77MB). Not images (only 527MB in containerd). Helm upgrade needs to run old+new pods simultaneously during rolling update, which requires scheduling new pods.
**Solution:** Immediate: `rm -rf /var/lib/apt/lists/*`, `journalctl --vacuum-size=20M`, `snap set system refresh.retain=2` — recovered ~400MB to 79%. Taint auto-cleared. Permanent: ANSIBLE-018 (maintenance playbook with systemd timer for weekly auto-cleanup on all nodes).
**Tags:** `#aws` `#k8s` `#disk` `#helm` `#maintenance`
