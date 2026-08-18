---
id: lesson-249-helm-upgrade-on-disk-constrained-node-creates
type: lesson
status: active
created: "2026-05-10"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Helm upgrade on disk-constrained node creates pull-evict-prune-pull death loop

**Context:** Post-merge of RELIAB-009 (PR #163): ran `make deploy-argocd` on aws1 (t4g.small, 8GB EBS) to apply §9.2 revisionHistoryLimit:3. Pre-deploy disk was 82% (within healthy range). Helm upgrade scaled the 6 Argo CD components back from 0 to 1 replica. New pods started pulling images (argocd v3.4.1 = 185MB + redis 8.2.3-alpine 27MB).
**Problem:** Image pulls pushed disk from 82% → 96% in ~30 seconds. Kubelet applied `node.kubernetes.io/disk-pressure:NoSchedule` taint. New Argo CD pods (without disk-pressure toleration) were evicted with `The node was low on resource: ephemeral-storage`. Evicted containers freed their image references → `crictl rmi --prune` (run by `make maintain` to recover disk) deleted those "orphan" images → next pod schedule attempt re-pulled the same images → death loop. The 8GB EBS volume is structurally insufficient: OS+apt cache (~1G) + K3s baseline (~2G containerd cache + kine + binaries) + Argo CD steady state (~3G) leaves <2G headroom — any image pull during normal operation crosses the 85% disk-pressure threshold.
**Solution:** Two complementary defenses: (1) Structural: increase EBS to 16GB via Terraform `ebs_size_gb` + online `aws ec2 modify-volume` + `sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/root` — no instance replacement needed (~$0.76/mo extra, gp3). (2) Operational: never run Helm upgrade on a node already above 80% disk; pre-flight cleanup BEFORE the upgrade not after; when disk-pressure taint is set, do NOT prune images (that worsens the loop) — instead let pods stay Pending while you free disk via logs/cache cleanup, taint clears automatically when disk drops below threshold. Detection: `kubectl describe node | grep -A2 Taints` and `df -h /` are the two signals to check before declaring a Helm upgrade healthy. Add Uptime Kuma alert at disk >75% as early warning.
**Tags:** `#aws` `#ebs` `#k3s` `#argocd` `#helm` `#disk-pressure` `#eviction` `#containerd` `#ephemeral-storage` `#incident`
