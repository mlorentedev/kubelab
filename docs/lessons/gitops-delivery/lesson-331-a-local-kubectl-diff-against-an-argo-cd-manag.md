---
id: lesson-331-a-local-kubectl-diff-against-an-argo-cd-manag
type: lesson
status: active
created: "2026-08-15"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# A local `kubectl diff` against an Argo CD-managed cluster describes a merge that will never happen

**Context:** prod was reporting OutOfSync and the question was narrow — does this need `make deploy-k8s ENV=prod`, or is Argo CD going to reconcile it on its own? The instinct was to look at the diff: `kubectl kustomize infra/k8s/overlays/prod | kubectl diff -f -`.

**Problem:** the diff came back enormous — every one of ~90 resources showed its `argocd.argoproj.io/tracking-id` annotation being removed. Read literally, prod had drifted wholesale and needed an urgent apply. That conclusion was wrong, and it was acted on before it was checked.

`kubectl diff` without `--server-side` simulates a **client-side** apply, whose three-way merge is computed against the live object's `kubectl.kubernetes.io/last-applied-configuration` annotation — not against `managedFields`. The rule it follows: a field present in that annotation but absent from the local manifest is proposed for deletion, while a field absent from *both* is left alone. Argo CD's applies write a last-applied configuration that includes `argocd.argoproj.io/tracking-id`; the manifest rendered locally from the overlay does not carry that annotation. So on every resource it lands in exactly the "present there, absent here" case. Nothing had drifted; the diff was reporting the difference between two apply strategies.

The repo's real deploy path never takes that strategy: `toolkit/cli/infra.py:784` sets `--server-side --force-conflicts --field-manager=kubelab-toolkit`. Server-side apply reasons over `managedFields` instead, and leaves fields the manifest does not submit untouched. `--force-conflicts` is not a free pass — it takes ownership of any field the manifest *does* submit and another manager owns, resolving the conflict by winning it. That is safe here only because the tracking annotation is never submitted in the first place. The diff was answering a question about a code path that is never executed.

Real drift, once measured properly, was **one** resource out of 91.

**Solution:** ask the component that owns the comparison. `kubectl get application kubelab-prod -n argocd -o json` — **pinned to the hub** with an explicit `--kubeconfig` or `--context`, since the Application object lives there and a current context aimed at a spoke returns the wrong answer or nothing at all — and read `status.resources[]`. That is Argo CD's own per-resource desired-vs-live verdict, computed by the controller doing the syncing. It named the single offending object immediately, without touching the spoke.

**Rule:**
- **On a cluster reconciled by Argo CD, the authority on "is this in sync" is the Application's `status.resources[]` on the hub — not a local diff.** Pin the query to the hub explicitly; the object does not exist on the spoke you are asking about.
- **If you do run `kubectl diff` against server-side-applied resources, pass the flags the real apply uses** (`--server-side --force-conflicts --field-manager=...`). Otherwise the output is a faithful description of an apply nobody will ever perform.
- **An annotation or label showing up as a deletion on *every* resource is a cue that the comparison is misconfigured — not proof of it.** A shared manifest or a cluster-wide policy change can legitimately touch everything, so uniformity is ambiguous on its own; genuine drift is merely *usually* lumpy. Treat it as the signal to go confirm against `status.resources[]`, never as the conclusion.

**Tags:** `#kubernetes` `#argocd` `#server-side-apply` `#field-manager` `#kubectl-diff` `#gotcha`

---
