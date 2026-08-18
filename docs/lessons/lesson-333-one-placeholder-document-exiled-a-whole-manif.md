---
id: lesson-333-one-placeholder-document-exiled-a-whole-manif
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, kubernetes, argocd, gitops, kustomize, traefik, sec-004, adr-047, gotcha]
---

# One placeholder document exiled a whole manifest from GitOps, and `Synced` said nothing

**Context.** SEC-004 (#970) applied a `rate-limit` middleware to every K3s IngressRoute. PR #1084 merged, `kubelab-prod` reported `Synced`/`Healthy` at exactly that revision, the static coverage test (`tests/test_rate_limit_coverage.py`) passed, and CI was green. Part 5 of the spec — "confirm every prod route carries it" — looked like a formality.

**Problem.** Prod's `argo.kubelab.live` route was running with `middlewares=['crowdsec-bouncer', 'secure-headers']`. No rate limit. It had been that way since the merge.

`infra/k8s/overlays/prod/argocd.yaml` held three documents — a Service, an EndpointSlice, and the IngressRoute. Only the **EndpointSlice** was unpublishable: it carries `RESOLVE_AWS1_TAILSCALE_IP`, because aws1 is a Spot instance whose Tailscale IP rotates on replacement. But the *whole file* had been excluded from the prod overlay (#152) as a blunt instrument for that one field. So Argo CD never managed any of it, its only apply path was `make deploy-argocd` (a hub-lifecycle operation nobody had reason to run for a middleware change), and the edit sat in git, applied to nothing.

**Why nothing reported it.** Three separate signals were all technically correct and all silent:

- **`Synced` speaks only for managed resources.** An Argo CD Application compares live against desired for what is in its source. A resource outside the overlay is not "drifted" — it is not in the comparison at all. `Synced` is not a statement about the cluster; it is a statement about a subset of it.
- **A static test that reads manifests tests git, not the cluster.** The file was correct. Every assertion about it passed, and would have kept passing forever.
- **The live object's own `last-applied-configuration`** still showed the pre-SEC-004 middleware list, and it had no `argocd.argoproj.io/tracking-id` — the two facts that identify this state — but nothing was looking at them.

**A wrong turn worth recording.** The first diagnosis was "implementation drift from ADR-047 D3", whose text says all three inline render sites migrate onto the `cluster_bootstrap` layer. The proposed fix was to add per-environment scoping (`envs:`) to that schema. Then `specs/TOOL-009-cluster-operator-bootstrap/tasks.md` T4 turned up: *"coredns is applied via the `cluster_bootstrap` loop; rpi3/aws1 EndpointSlices via a small toolkit command each"* — the split was a recorded decision, not drift, and the proposed fix would have contradicted it. **An ADR's prose can be narrower than it reads; the spec that implemented it is where the disambiguation lives.**

**Fix (#1089).** Split the file so only the EndpointSlice stays out-of-band. The Service and IngressRoute joined the prod overlay — which is what `overlays/prod/headscale.yaml` (same Service + EndpointSlice + IngressRoute shape) already did, because the VPS IP is stable enough to commit. The route then reached prod through GitOps on the next sync, with no manual deploy and no new Makefile target.

**Rules.**

- **A file is not the unit of GitOps exclusion — a document is.** Before exiling a multi-document manifest, check which documents actually cannot be committed. Usually it is one.
- **`Synced` is not "the cluster matches git."** It is "the resources this Application manages match git." Whenever the answer to "did the change arrive?" matters, ask what is *not* in the source before trusting the status.
- **A guard that reads manifests cannot fail on this class of defect** — the manifest is the thing that is right. Pair it with one that reads the cluster (`tests/infra/test_rate_limit.py`) and one that fails when a manifest is applied by nothing at all (`tests/test_orphan_manifests.py`).
- **Out-of-band manifests are legitimate; silent ones are not.** Where a resource genuinely cannot be committed, make it name the command that applies it, and assert that command still exists — otherwise the note outlives the target it describes.

**Tags:** `#kubernetes` `#argocd` `#gitops` `#kustomize` `#traefik` `#sec-004` `#adr-047` `#gotcha`
