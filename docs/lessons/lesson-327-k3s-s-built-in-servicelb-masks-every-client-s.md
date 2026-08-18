---
id: lesson-327-k3s-s-built-in-servicelb-masks-every-client-s
type: lesson
status: active
created: "2026-08-14"
owner: manu
tags: [kubelab, lesson, k3s, networking, servicelb, klipper-lb, sec-004, gotcha]
---

# K3s's built-in ServiceLB masks every client's real IP — `externalTrafficPolicy: Local` cannot fix it

**Context:** SEC-004 — before adding any rate-limit middleware to K3s Traefik, checking whether a per-client-IP `sourceCriterion` would actually see distinct client IPs.

**Problem:** it does not. A request from a known source IP (verified via `tailscale ip -4`) reached Traefik's access log tagged with an internal pod-CIDR address instead — and a different one on a second, near-simultaneous request. The standard first fix for source-IP mangling behind a Kubernetes `LoadBalancer` Service, `externalTrafficPolicy: Local` (skips kube-proxy's SNAT for cross-node delivery), was tried and changed nothing.

The actual cause sits one layer below kube-proxy entirely: K3s's built-in ServiceLB (`klipper-lb`) is not a real load balancer, it is a per-node `iptables` script. Reading its container logs directly (`kubectl logs <svclb-pod> -c lb-tcp-443`) showed the exact rules it installs for every `LoadBalancer` Service:

```shell
iptables -t nat -I PREROUTING -p TCP --dport 443 -j DNAT --to <service-clusterIP>:443
iptables -t nat -I POSTROUTING -d <service-clusterIP>/32 -p TCP -j MASQUERADE
```

The `POSTROUTING ... MASQUERADE` rule is unconditional — every packet reaching that Service's ClusterIP gets its source rewritten, regardless of `externalTrafficPolicy`, because the rewrite happens at the klipper-lb hostPort DNAT hop, before the packet is anywhere near the Service or kube-proxy's own forwarding logic. This is klipper-lb's documented design (it avoids asymmetric routing without needing anything smarter than raw NAT), not a misconfiguration — so there is no flag to flip; the fix is a different ServiceLB implementation (e.g. MetalLB) entirely.

**Solution:** not fixed — filed as its own prerequisite issue (kubelab#1067) rather than attempted inline, since the real remediation is an infrastructure-level replacement affecting every `LoadBalancer` Service in the cluster, not a K3s Traefik config change. The ticket this was discovered under (SEC-004, rate-limit middleware) was rescoped to a global, non-per-client limit as a direct, documented consequence rather than shipping a per-IP limiter that silently buckets everyone together.

**Rule:**
- **Before designing anything keyed on "the client's IP" behind K3s's default `LoadBalancer` implementation, verify empirically what Traefik actually sees — do not assume `externalTrafficPolicy: Local` is sufficient.** It is the correct fix for kube-proxy-level SNAT, and irrelevant to klipper-lb's own masquerade, which happens upstream of that layer. Test with a temporary `--accesslog=true` and a real request from a known source, not by reading Kubernetes docs about `externalTrafficPolicy` in isolation.
- **"We already have CrowdSec" does not mean client-IP visibility is a solved problem for every future feature.** CrowdSec's bouncer plugin consumes application-level decisions from its own LAPI and doesn't need Traefik's view of source IP the same way a `sourceCriterion`-based rate limiter would — the two security layers have different dependencies on this fact, and assuming one implies the other is how this would have shipped broken.
- **A finding that changes a ticket's feasible scope belongs in that ticket and a dedicated follow-up issue, not folded silently into "ship what we can."** Global vs. per-client rate limiting are different guarantees; conflating them in the PR description would have overstated what the feature actually protects against.

**Tags:** `#k3s` `#networking` `#servicelb` `#klipper-lb` `#sec-004` `#gotcha`

---
