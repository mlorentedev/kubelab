---
id: lesson-286-build-once-re-tag-adr-056-read-the-raw-stagin
type: lesson
status: active
created: "2026-06-27"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery]
---

# Build-once re-tag (ADR-056): read the raw staging pin, protect it from the prune, copy the manifest list

**Context:** Implementing build-once for the `api` image (DELIVERY-002) — prod semver produced by re-tagging the staging-validated `sha-<short>` instead of rebuilding from the release commit (closes the parity gap that CrashLooped the first gated promotion, #666/#679).

**Problem:** Three non-obvious traps. (1) Resolving the sha from the *merged* config surfaces the inherited `dev` from `common.yaml`, masking "staging has no validated artifact" — the resolver would happily re-tag `dev`. (2) The weekly prune janitor (`ci-cleanup.yml`) keeps only the N most-recent `sha-*` and could delete the sha a pending prod promotion still references. (3) A naive `docker pull && docker tag && push` collapses a multi-arch manifest list to a single arch.

**Solution:** (1) Read the **raw** `apps.platform.<app>.version` straight from `values/staging.yaml` and require `^sha-[0-9a-f]{7,}$` — an absent pin is an error, not a silent `dev`. (2) Thread a `protected` set through the pure `select_stale_tags`; the CLI gathers per-app sha pins from staging+prod values so a tag referenced by a committed overlay is never pruned, even outside the retention window. (3) Use `docker buildx imagetools create -t dst src` — a registry-side manifest-list copy (no QEMU, no rebuild), then assert `imagetools inspect --format '{{.Manifest.Digest}}'` equality and fail the release on mismatch.

**Rule:** Re-tag by digest, never rebuild, to ship the validated bytes. Resolve promotion sources from the raw env SSOT (absence must error, not inherit). Any janitor that prunes by recency must exempt state still referenced by committed config. `errors` (edge infra) stays on its rebuild — build-once's value is near-zero for static pages with no staging-validated artifact to lose.

**Tags:** `#delivery` `#ci-cd` `#gitops` `#build-once` `#docker` `#adr-056`
