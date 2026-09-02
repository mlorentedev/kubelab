---
id: lesson-410-a-healthy-pod-does-not-prove-an-app-read-its-config
type: lesson
status: active
created: "2026-08-31"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, vikunja, r2, s3, config-verification]
---

# A healthy pod does not prove an app read its config — an unrecognized env var can fail silently

**Context**: Wiring Cloudflare R2 file storage into Vikunja (`infra/k8s/base/services/vikunja.yaml`). The ConfigMap set `VIKUNJA_FILES_S3_ENABLED: "true"` plus `VIKUNJA_FILES_S3_ACCESSKEYID`/`SECRETACCESSKEY` in the Secret. The pod came up `1/1 Running`, no crash loop, no errors in the logs. Treated that as verification that R2 was working.

**Problem**: None of those three env var names exist in Vikunja's config schema. Confirmed against the 1.0.0 source (`pkg/config/config.go`): the storage backend toggle is `files.type` (`"local"`/`"s3"`), not a `files.s3.enabled` key, and the credential fields are `files.s3.accesskey`/`files.s3.secretkey`, not `accesskeyid`/`secretaccesskey`. Vikunja's config loader (viper) silently ignores keys it doesn't recognize — no warning, no error, no metric. So `files.type` kept defaulting to `"local"` regardless of what `VIKUNJA_FILES_S3_ENABLED` was set to. This had been true since the feature first shipped; the pod stayed healthy through every deploy because local storage always works. It only surfaced when the operator uploaded a real attachment and it did not appear in the R2 bucket listing — a downloadable-from-the-app check had *also* passed, because Vikunja was serving the file straight from local disk.

**Solution**: Verified the actual config keys against the Go source directly rather than assuming (three independent fetches converged: the docs page, the raw Go struct, and re-checking against the same source). Corrected the ConfigMap to `VIKUNJA_FILES_TYPE: "s3"` and the Secret mapping to `VIKUNJA_FILES_S3_ACCESSKEY`/`SECRETKEY`. Confirmed by the only test that actually proves it: the operator uploaded a file and it appeared in the Cloudflare R2 bucket listing directly, independent of the app.

**Rule**: For any config surface where the consuming app doesn't validate unknown keys (env-var-driven config via viper, python-dotenv, or similar loose loaders), a healthy pod and even "the app appears to use the feature" are not evidence the config took effect — a typo'd key just silently falls back to the default. Verify by observing the actual side effect one layer below the app (an object in the destination bucket, a row in the destination table, a request in the upstream's own access log), not by asking the app whether it worked. Before wiring a third-party app's config from scratch, pull the literal key names from its source or schema — not from a docs page's prose, which can describe an aspirational or differently-versioned format.

**Tags**: `#vikunja` `#r2` `#s3` `#config-verification` `#pr-1521`
