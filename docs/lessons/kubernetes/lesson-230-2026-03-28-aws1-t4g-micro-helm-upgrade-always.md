---
id: lesson-230-2026-03-28-aws1-t4g-micro-helm-upgrade-always
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# 2026-03-28: aws1 t4g.micro Helm upgrade always causes swap thrashing — mitigate before deploy

**Symptom:** Every `make deploy-argocd` on aws1 (1GB RAM) causes Helm upgrade timeout. K8s API becomes unresponsive for 10-15 minutes. Pods enter CrashLoopBackOff. Happened 2026-03-27 (disk-pressure) and 2026-03-28 (RBAC deploy).

**Root cause:** Helm upgrade loads all CRDs + current state into memory. ArgoCD has heavy CRDs (Applications, ApplicationSets, AppProjects). On 1GB RAM, this pushes into swap → all K8s processes slow → liveness probes fail → restart loops → more memory pressure.

**Mitigation pattern (add to deploy-argocd Makefile target):**
1. Pre-scale: `kubectl scale deploy argocd-applicationset-controller --replicas=0` (saves ~100MB)
2. Set Helm timeout: `--timeout 10m` (don't fail on slow API)
3. Post-scale: restore applicationset-controller after upgrade
4. Add `--wait` so Helm confirms pods are healthy before returning

**Long-term fix:** Upgrade to t4g.small (2GB RAM, ~$7/mo). The $3.40/mo delta eliminates the problem entirely.

**NEVER do during aws1 Helm upgrade:** kubectl patch, rollout restart, or any additional kubectl commands — they compound the memory pressure.

**Final pattern (2026-03-28b):** Pre-scale ALL to 0 (not just applicationset) + wait for termination + Helm upgrade with 5min timeout. Pods parados = Helm tiene toda la RAM disponible. Downtime ~2-3 min — acceptable for solo operator. Partial scale-down (only applicationset) was NOT enough — still OOM'd twice.
