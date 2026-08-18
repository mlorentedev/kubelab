---
id: lesson-026-argo-cd-hub-oom-cascade-on-aws1-t4g-small-spo
type: lesson
status: active
created: "2026-05-06"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Argo CD hub OOM cascade on aws1 (t4g.small Spot)

**Context**: aws1 (Argo CD hub on AWS, t4g.small Spot, 2 GB RAM with 2 GB swap) became unreachable after 12h uptime. `argo.kubelab.live` returned timeouts then 502. Tailscale showed aws1 as offline ~6h. SSH refused.

**Problem**: EC2 status `running / impaired`. Console output showed `Out of memory: Killed process 19332 (coredns)`. CoreDNS death cascaded: cluster DNS dead → controllers retry-loop → memory pressure → systemd unable to create cgroup slices for new pods → kubelet stuck → Tailscale heartbeat starved → instance marked impaired by AWS. Underlying enabler: hundreds of zombie `argocd-applicationset-controller` pods (statuses `Completed`/`ContainerStatusUnknown`/`ContainerCreating` from 9-14 days ago) inflating etcd and apiserver list bandwidth. K3s default `terminated-pod-gc-threshold=12500` never triggered cleanup on a 1.8 GB node. No resource `limits` on Argo CD components — OOM Killer picked CoreDNS at random.

**Solution**: (1) Reboot via `aws ec2 reboot-instances` to clear wedged kernel. (2) Scale all Argo CD Deployments + StatefulSet to `replicas=0` to relieve immediate memory pressure (persists in etcd, survives reboot). (3) Second reboot on the now-quiet system for a clean K3s baseline. Argo CD remained at 0 replicas overnight; `argo.kubelab.live` returning 502 was the accepted trade-off until the permanent fix lands as RELIAB-009.

**Rule**: For undersized nodes (< 4 GB) running Helm-managed control planes, three configuration changes are non-optional:
1. Explicit resource `requests` + `limits` on every Deployment. Without them, OOM Killer chooses victims at random and kernel-critical pods (CoreDNS, kubelet daemonsets) die first instead of the offender.
2. `revisionHistoryLimit: 1` on all Deployments to bound the ReplicaSet graveyard. Default 10 multiplies pod-object pressure on etcd.
3. Override K3s `--kube-controller-manager-arg=terminated-pod-gc-threshold=N` to ≤ 200. The 12500 default assumes large clusters.

Operational note: for "always-on" workloads on Spot, design for the fact that AWS will reclaim. Stable identity comes from Tailscale MagicDNS (`<host>.kubelab.internal`), never public IPs. The first proximate signal of a wedged spot is `tailscale status` showing the node as `offline, last seen Nh ago` while EC2 still reports `running / impaired` — combined, that pair is diagnostic.
