---
id: lesson-328-kubectl-apply-cannot-convert-a-service-with-a
type: lesson
status: active
created: "2026-08-14"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# `kubectl apply` cannot convert a Service with a selector into a selector-less one — omitting a field is not deleting it

**Context:** ADR028-004 / #1062 moved Gitea out of K3s onto the Beelink and kept its domain, replacing the in-cluster workload with the repo's external-service pattern — `Service` (no selector) + hand-written `EndpointSlice` → the node's Tailscale IP. The manifest was correct, both overlays rendered clean, `make test-fast`, `make validate-sync` and staging e2e were green, and the first post-apply probe of `gitea.kubelab.live` returned the Beelink's instance. Everything said the cutover had worked.

**The trap:** it hadn't. The live Service still carried `selector: {app.kubernetes.io/name: gitea}` from its previous life. `kubectl apply` did not remove it, because the new manifest does not *set* `selector: null` — it simply has no `selector` key, and the field remained owned by whichever manager wrote it originally. So the endpoints controller went on managing its own slice next to the manual one:

```
NAME             ADDRESSES      PORTS
gitea-external   [100.64.0.3]   3000     # the Beelink, from git
gitea-qwcfk      [10.42.0.11]   3000     # the old in-cluster pod, still selected
```

Two EndpointSlices behind one Service means Traefik round-robins — so the domain served **two different Gitea instances, alternately**, each with its own database. Not a 502 anyone would notice: a push landing in one and a read served from the other. The single verification request that "confirmed" the cutover had a 50% chance of being right, and was.

The manifest is not wrong, and on a fresh cluster it produces exactly the intended object. The defect only exists in the *conversion*: an object that already had a selector cannot lose it by omission.

**Fix:** `kubectl patch svc gitea --type=merge -p '{"spec":{"selector":null}}'` — an explicit null is the only way to express removal — plus scaling the retired Deployment to 0 so the controller-managed slice emptied. Re-verified with **12 consecutive requests, 12/12 hitting the Beelink**, discriminated by the admin account's creation timestamp rather than by "it responded".

**Rule:**
- **When a live object is being converted rather than created, ask which fields the old shape had that the new one merely omits.** Strategic-merge apply treats absent and null as different things, and only one of them deletes. This is the same shape as the ADR-037 `certResolver: null` gotcha already in CLAUDE.md — an empty map means "change nothing", not "remove".
- **Verify a cutover with repeated requests and a discriminator that identifies *which backend answered*, never with one request and a 200.** Round-robin between an old and a new backend is indistinguishable from success in any single sample. Pick a field the two instances cannot both have — here, the admin account's creation date, 146 days apart.
- **Count EndpointSlices per Service after any switch to the external-service pattern.** `kubectl get endpointslice -l kubernetes.io/service-name=<svc>` must return exactly the hand-written one; a second, controller-managed slice is the tell that the Service still has a selector.

**Tags:** `#kubernetes` `#service` `#endpointslice` `#kubectl-apply` `#cutover` `#adr-061` `#gotcha`

---
