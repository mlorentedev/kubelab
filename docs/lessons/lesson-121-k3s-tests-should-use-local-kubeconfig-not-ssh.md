---
id: lesson-121-k3s-tests-should-use-local-kubeconfig-not-ssh
type: lesson
status: active
created: "2026-03-15"
owner: manu
tags: [kubelab, lesson, testing, k3s, kubectl, ssh]
---

# K3s tests should use local kubeconfig not SSH+sudo

**Context:** Running infra tests against K3s cluster from workstation
**Problem:** K3s tests SSH'd to k3s-server and ran `sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml`. This fails in BatchMode SSH because sudo requires a terminal for password input. All 4 K3s tests failed.
**Solution:** Use local kubeconfig (`~/.kube/kubelab-config`) with kubectl directly from workstation. No SSH needed — kubectl connects to K3s API via Tailscale. Simpler, faster (0.66s vs 44s), no sudo issues.
**Tags:** `#testing` `#k3s` `#kubectl` `#ssh`
