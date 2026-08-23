---
id: lesson-374-a-comment-claiming-another-target-does-it-is-not-a-chain
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, makefile, terraform, spot]
---

# A comment claiming another target already does it is not a chain

**Context**: Reconstructing the lost Terraform state for the GCP hub root. Adopting
the instance template forces its replacement (GCP does not return `name_prefix`, so
Terraform reads `null -> "gcp1-"` on a ForceNew field), and the MIG updates
`PROACTIVE` / `REPLACE`, so the apply rolled `gcp1`. That rotated its Tailscale
address, `100.64.0.12 -> 100.64.0.13`.

**Problem**: `argo.kubelab.live` went dark while the hub itself was perfectly
healthy — `100.64.0.13:30080` answered HTTP 200 and MagicDNS already resolved
`gcp1.kubelab.internal` to the new address. Only prod's `argocd-external`
EndpointSlice still held `.12`, because an EndpointSlice takes an IP and cannot
take a DNS name. That object is rendered from a `RESOLVE_GCP1_TAILSCALE_IP`
placeholder, and its own comment says the render is run by `deploy-argocd`,
"exactly the step `make gcp1-replace` already tells you to run after a recreate".

It does not. `gcp1-replace` runs `gcp-recreate`, `wait-node-ready` and `provision`,
then echoes "Argo CD is installed by cloud-init" — it never invokes `deploy-argocd`
and never mentions it. The comment described an automation that was never wired,
and the recreate is the one event that invalidates the value.

**Solution**: repointed with the same command `deploy-argocd` runs, rather than the
ten-minute Helm upgrade around it, since Argo CD was already installed and serving:

```
poetry run toolkit infra k8s render-apply --env prod --optional \
  --manifest infra/k8s/overlays/prod/argocd-endpointslice.yaml \
  --render RESOLVE_GCP1_TAILSCALE_IP=gcp1.kubelab.internal
```

Verified by identity, not by status code — both hubs answer 200 on that NodePort,
so the code proves nothing. The SHA-256 of the body served publicly matched the one
served by `100.64.0.13` directly (`53a01d03…`), and the live EndpointSlice read
back `100.64.0.13`.

**Rule**: a comment asserting that another target performs a step is documentation,
not a dependency — grep the target before trusting it. The tell is a comment that
names a second target in the present tense ("which is exactly the step X already
runs"); if the chain were real it would be a line of code you could point at.
Prefer wiring the step and letting the comment name the wiring.

Two corollaries this incident earned:

- **A routine unattended event must not require a human to remember a command.**
  This hub is Spot: a preemption performs the same recreate, at night, with nobody
  watching. Extracting the render into its own target and calling it from
  `gcp1-replace` fixes the *deliberate* recreate only — a real preemption runs no
  Makefile at all, and prod's route stays dead until somebody notices. That gap is
  narrowed by the target, not closed by it.
- **`--optional` belongs to a render that may legitimately be skipped, never to
  one that repairs a broken route.** It reports success on a failed render, which
  in this context would leave prod pointing at a dead address under a green tick.

**Tags**: `#argocd` `#endpointslice` `#spot` `#makefile` `#gcp-001`
