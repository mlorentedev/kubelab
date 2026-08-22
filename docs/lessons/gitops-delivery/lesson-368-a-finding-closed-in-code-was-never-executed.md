---
id: lesson-368-a-finding-closed-in-code-was-never-executed
type: lesson
status: active
created: "2026-08-22"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, gcp, cloud-init, argocd]
---

# "Closed in code" is not closed, and the gap is invisible until something runs

**Context**: GCP-001 finding **F1**: a managed instance group *recreates* rather
than restarts, so every preemption is a from-scratch boot. A hub whose
cloud-init stops at "K3s ready" never comes back — the MIG restores the VM, not
the hub. The fix was for cloud-init to install Argo CD itself on every boot.

PR #1217 implemented it and recorded **"F1 closed in code"**. Three PRs and a
merged spec update later, that phrasing had become "F1 is closed".

**Problem**: The first real boot ended with `cloud-init status: error` and zero
Argo CD pods, on a node the MIG reported as perfectly healthy:

```
Error: Kubernetes cluster unreachable: Get "http://localhost:8080/version":
dial tcp [::1]:8080: connect: connection refused
```

`localhost:8080` is helm's fallback when it finds **no kubeconfig**. Nothing in
the script exported `KUBECONFIG`.

The reason it looked correct is worth more than the bug. `kubectl` runs earlier
in the same script and works — because K3s ships a wrapper that defaults to
`/etc/rancher/k3s/k3s.yaml`. Every `kubectl` line was fine. **helm has no such
convention**, so the one tool that needed the path was the one nobody had given
it to.

So the script was correct **by accident** for its first half, and reviewing it
confirmed that impression: the namespace creation right above the helm call
demonstrably worked.

**Solution**: One line, before the first `kubectl` rather than merely before
helm, so the script stops depending on a convenience wrapper:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
```

Proven the only way it could be — by recreating the node and watching it rebuild
unattended: `cloud-init status: done`, six Argo CD pods, no human involved.

**Rule**: **"Closed in code" is a status for the code, not for the finding.** A
finding about runtime behaviour closes when the runtime has behaved, and the
distance between those two is invisible: nothing goes red, no test fails, the
PR merges, and the spec starts saying the thing is done.

Two habits that would have caught it, both cheap:

- **Say which one you mean.** "Implemented, unverified" and "closed" are
  different states. #1217 said the first and the repository read the second,
  because the phrase invited it.
- **When a script mixes tools, ask which of them share configuration.** `kubectl`
  and `helm` both talk to the same cluster and discover it differently. A script
  that works for one is not evidence for the other, and "the command above it
  worked" is the reasoning that hides it.

Same shape as [[lesson-366]] one file over: a belief encoded, documented, and
green, because nothing had run it.

**Tags**: `#gcp` `#cloud-init` `#argocd` `#f1` `#pr-1263`
