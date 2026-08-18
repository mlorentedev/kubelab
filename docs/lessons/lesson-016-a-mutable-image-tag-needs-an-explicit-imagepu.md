---
id: lesson-016-a-mutable-image-tag-needs-an-explicit-imagepu
type: lesson
status: active
created: "2026-06-15"
owner: manu
tags: [kubelab, lesson]
---

# A mutable image tag needs an explicit `imagePullPolicy: Always` or it never re-pulls

**Context**: Both prod and staging ran the mutable `:dev` tag with `imagePullPolicy` never declared in the manifests. Staging silently defaulted to `IfNotPresent` and never re-pulled a freshly-pushed `:dev` — WEB-011 changes were not appearing on staging.

**Problem**: Kubernetes defaults `imagePullPolicy` to `IfNotPresent` for any tag other than `latest`. A mutable tag like `:dev` therefore sticks to whatever image the node first cached; new pushes to the same tag are ignored until the node forgets the image. The 2026-03-16 lesson about this had been learned but never enforced in the generator.

**Solution**: #657 (PR-B) — the generator now sets `imagePullPolicy` tag-aware: mutable tags (`dev`/`latest`/`*-rc.*`) → `Always`; immutable tags (`sha-*`/semver) → `IfNotPresent`. This unblocked the staging refresh and is the foundation for the ADR-046 model (immutable tags everywhere, so a tag change is always a real pull Argo reconciles).

**Rule**: Never run a mutable tag without `imagePullPolicy: Always`, and never leave `imagePullPolicy` to the default. Better still: prefer immutable tags (`sha-<short>`, semver) so the desired state *is* the tag — a change always forces a pull, `IfNotPresent` is correct, and `Always` is unnecessary.

**Tags**: `#kubernetes` `#imagepullpolicy` `#mutable-tags` `#adr-046` `#pr-657`
