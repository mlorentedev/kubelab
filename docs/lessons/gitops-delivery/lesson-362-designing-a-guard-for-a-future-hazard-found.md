---
id: lesson-362-designing-a-guard-for-a-future-hazard-found
type: lesson
status: active
created: "2026-08-21"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, helm, versioning]
---

# Designing a guard for a future hazard found it already loaded and aimed at prod

## What happened

Writing the GCP hub's cloud-init, the plan called for pinning the Argo CD Helm
chart. The reasoning was about the *future* machine: a managed instance group
recreates on every preemption, so an unpinned `helm upgrade --install` would make
a 3am Spot interruption also an unattended chart upgrade.

Deciding which version to pin required knowing what was actually deployed. One
read-only query answered it and changed the ticket:

```
$ helm list -n argocd --kubeconfig ~/.kube/kubelab-hub-config -o json
[{"name":"argocd","revision":"16","updated":"2026-05-10 21:25:21",
  "chart":"argo-cd-9.5.13","app_version":"v3.4.1"}]

$ helm search repo argo/argo-cd --versions | head -2
argo/argo-cd   10.4.0   v3.5.1
```

`aws1` — the **live** hub, managing prod — was running chart `9.5.13` while the
repository served `10.4.0`. And `_deploy-argocd-helm` ran
`helm upgrade --install argo/argo-cd` with **no `--version`**, which helm resolves
to the newest chart available.

So the next `make deploy-argocd` — run for any reason at all, including a routine
OIDC secret refresh, by anyone — would have carried prod's management plane
across a major version boundary **as a side effect of an unrelated deploy**.

The hazard being designed against for a machine that does not yet exist was
already live, on the machine that does.

## Why it stayed invisible

Nothing about the existing setup looked wrong. The hub was healthy, the deploy
target worked, and it had worked the last sixteen times. An unpinned dependency
does not fail when you introduce it — it fails on some later, unrelated
invocation, and the blast radius grows with the gap since the last deploy. Three
months of not deploying is three months of accumulating upgrade.

The Makefile also *read* as deliberate: it carefully validated four secrets and
refused to install on an empty decrypt. Care in one dimension is easily mistaken
for care in all of them.

## The pin goes to what is RUNNING, not to what is newest

This is the part worth carrying, because the wrong choice looks more responsible.

Pinning to `10.4.0` would have **performed** the upgrade while appearing to
prevent it — the commit message would say "pin the chart" and the effect would be
a major version jump on the next deploy. Pinning to `9.5.13` freezes today's
reality and makes the upgrade a decision someone takes deliberately, with the
release notes open (filed as #1209).

A pin's job is to stop things moving without anyone choosing. Setting it to
whatever is current at pinning time does the opposite one final time.

## What to do

- **Before pinning any dependency, measure what is deployed.** The pin is only
  a no-op if it matches reality, and only a no-op pin is safe to land without
  reading release notes.
- **Treat an unpinned dependency in a deploy path as a live defect**, not as a
  tidiness issue. Its failure is deferred and its trigger is unrelated to it.
- **When designing a guard for a hypothetical machine, check the real one.**
  The unattended future case is often the supervised present case with the
  supervision removed — and the supervision may already be doing nothing.

## Guard

`tests/test_secrets_argocd_catalog.py::TestTheChartVersionIsPinned` asserts the
SSOT declares an exact version (rejecting a range or `latest`) and that the
deploy target reads it rather than carrying a duplicate literal. The version is
declared once in `argocd.chart_version`, read today by the operator path
(`_deploy-argocd-helm`) and by the unattended one (the GCP hub's cloud-init) when
that lands, so the two installs cannot disagree about what "Argo CD" means.

Both assertions were confirmed to fail before being trusted: unpinning the helm
call and setting the SSOT to `latest` produced exactly two failures.

## See also

- `docs/adr/adr-063-hub-cloud-provider-migration.md` — the MIG recreate model
- Issue #1209 — the 9.x → 10.x move, as a deliberate change
