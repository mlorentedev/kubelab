---
id: lesson-010-sops-matches-sops-yaml-path-regex-against-the
type: lesson
status: active
created: "2026-06-20"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, windows, cross-platform, secrets, toolkit, pr-721]
---

# SOPS matches `.sops.yaml` path_regex against the basename on Windows

**Context**: Provisioning `infra.postgres.password` for staging + prod (#720/#721) from the Windows workstation. Every `toolkit secrets {init,apply,show,audit}` call failed with `no matching creation rules found`, blocking all secret operations.

**Problem**: `.sops.yaml` anchored its rule on a directory prefix — `path_regex: infra/config/secrets/.*\.enc\.yaml$`. On Windows, sops applies `path_regex` to the file **basename** (`staging.enc.yaml`), not the repo-relative path, so a prefix-anchored regex never matches there. On Linux/CI the same rule matched (full path), so the breakage was effectively Windows-only and invisible in CI. Worse second-order effect: the false "no rule" made the toolkit read every secret as **missing** (decryption silently failing), so `toolkit secrets init` was about to *rotate the 12 existing secrets*. Stopped before running it.

**Solution**: Match by extension only — `path_regex: .*\.enc\.yaml$` and `.*\.pem(\.enc)?$`. The only encrypted files in the repo live under `infra/config/secrets/`, so an extension match is equivalent on Linux/CI and also works on Windows. After the fix a dry-run confirmed only `infra.postgres.password` would be generated (no rotation).

**Rule**: Never anchor a `.sops.yaml` `path_regex` on a directory prefix if the workflow ever runs on Windows — sops matches the basename there, not the path. Use a basename-stable pattern (extension). And: when a secret tool reports a secret "missing", verify *decryption itself works* before any `generate`/`init`/rotate — a decrypt failure masquerades as absence, and rotation is destructive.

**Tags**: `#sops` `#windows` `#cross-platform` `#secrets` `#toolkit` `#pr-721`
