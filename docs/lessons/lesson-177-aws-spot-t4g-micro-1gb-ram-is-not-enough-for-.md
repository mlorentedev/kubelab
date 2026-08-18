---
id: lesson-177-aws-spot-t4g-micro-1gb-ram-is-not-enough-for-
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, aws, k3s, spot, memory, swap]
---

# AWS Spot t4g.micro: 1GB RAM is NOT enough for K3s + Argo CD without swap

**Context:** K3s alone consumes ~750MB on t4g.micro (1GB total). Installing Argo CD (~576MB) caused OOM, killing sshd and making the instance unreachable.

**Solution:** Add 2GB swap via cloud-init `swap:` directive. Must be in cloud-init (not manual) so it survives Spot restarts.

**Rule:** Always provision swap on t4g.micro for K3s workloads. Monitor with `free -m`. Upgrade to t4g.small (2GB) if swap usage is consistently >50%.
**Tags:** `#aws` `#k3s` `#spot` `#memory` `#swap`
