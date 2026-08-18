---
id: lesson-232-2026-03-28-t4g-micro-cannot-survive-repeated-
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-28: t4g.micro cannot survive repeated Helm upgrade retries — stop after first failure

**Symptom:** 4 consecutive deploy-argocd attempts. Each one compounds memory pressure. By attempt 4, K3s API server was completely unresponsive (TLS handshake timeout). Required AWS console reboot.

**Rule:** After a failed Helm upgrade on t4g.micro:
1. Reboot the instance (AWS console or `aws ec2 reboot-instances`)
2. Wait for K3s to come back (~2-3 min)
3. `make recover-argocd` (clean Helm state)
4. ONE `make deploy-argocd` attempt
5. If that fails → upgrade to t4g.small, don't retry

**Never:** Retry Helm upgrade on an already-stressed t4g.micro. Each retry makes it worse.
