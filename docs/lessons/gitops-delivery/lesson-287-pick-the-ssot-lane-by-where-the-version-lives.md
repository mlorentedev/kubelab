---
id: lesson-287-pick-the-ssot-lane-by-where-the-version-lives
type: lesson
status: active
created: "2026-06-27"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Pick the SSOT lane by where the version lives, not by "it's a custom app" (DELIVERY-003)

**Context:** Automating the `errors` edge image tag (#776). The instinct was to treat it like api/web — add it to `toolkit deployment promote`'s per-env overlay lane.

**Problem:** That's the wrong lane. `errors` pins a *single* `edge.errors.version` in `common.yaml`, shared across all envs — structurally identical to the third-party images (`gitea`, `n8n`…) that `sync_k8s_images.py` already syncs into `base/kustomization.yaml` from common.yaml. api/web are different: their tags live *per-env* in the overlays (`apps.platform.<app>.version` in staging/prod.yaml) and ride `promote` + the K8s generator. Forcing errors onto the promote lane would have invented a per-env split it doesn't have (and the spec's "single SSOT" goal forbids).

**Solution:** Route by SSOT *location*. errors → the **sync** lane: emit it from the structured `edge.errors` keys (`{registry}/{image_name}:{version}`), delete its hardcoded `newTag`, let `sync_k8s_images` own it. `promote --app errors` writes `common.yaml` + re-syncs (env-agnostic, `--env` ignored), never touches an overlay. Note: `sync_k8s_images`'s block-replace regex stops at the `# Custom apps` comment, so web/api stay hand-pinned below while errors joins the synced block above.

**Rule:** Before automating a deploy tag, ask *where does this version live* — one shared key in common.yaml (→ sync lane, like third-party) or per-env in the overlays (→ promote lane, like api/web). The runtime (edge vs platform) is a red herring; the SSOT shape is what decides. Caveat: the drift gate covers the generator (overlays) but NOT the kustomization sync — a manual bump-without-sync isn't caught (tracked: #792).

**Tags:** `#delivery` `#ci-cd` `#ssot` `#kustomize` `#gitops` `#adr-046`
