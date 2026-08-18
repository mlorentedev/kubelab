---
id: lesson-184-t4g-micro-spot-sizing-fits-argo-cd-not-helm-u
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# t4g.micro Spot sizing: fits Argo CD, not Helm upgrades

**Context**: Running Argo CD hub on t4g.micro (1GB RAM, 2GB swap, 1 vCPU).

**Problem**: Multiple Helm upgrades, Redis flushes, and pod restarts in one session caused swap thrashing (925MB swap used), K3s API timeouts, and a 10+ min recovery cycle. T-series burst credits also exhausted — CPU throttled to 10%.

**Solution**: 1GB fits Argo CD in steady state (5 pods, ~600MB total). For heavy operations (Helm upgrades, bulk restarts), space them out. Never batch 3+ pod restarts on the micro. If recurring, temporary scale to t4g.small ($7/mo) during maintenance windows.

**Rule**: Treat the micro as a steady-state-only box. Maintenance operations are the risk, not normal operations. Plan upgrades as discrete, spaced events.
