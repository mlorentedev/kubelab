---
id: lesson-185-argo-cd-resource-exclusions-selector-may-not-
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Argo CD resource.exclusions selector may not work

**Context**: Trying to exclude only auto-managed EndpointSlices while allowing manual ones.

**Problem**: Set `resource.exclusions` with `selector.matchLabels` to filter by the `endpointslice.kubernetes.io/managed-by` label. Argo CD still excluded ALL EndpointSlices regardless of selector.

**Solution**: Set `resource.exclusions: ""` (empty string) to remove all default exclusions. Manual EndpointSlices for external services are safe because Argo CD's `prune: true` only deletes resources with its own tracking label — it won't touch auto-managed EndpointSlices created by K8s.

**Rule**: Don't rely on `selector` in `resource.exclusions` for fine-grained filtering. Use empty exclusions + prune safety instead.
