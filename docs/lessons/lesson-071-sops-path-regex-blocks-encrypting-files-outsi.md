---
id: lesson-071-sops-path-regex-blocks-encrypting-files-outsi
type: lesson
status: active
created: "2026-02-25"
owner: manu
tags: [kubelab, lesson]
---

# SOPS path_regex Blocks Encrypting Files Outside Defined Paths

**Context**: Trying to encrypt a secrets file created in `/tmp/` for testing before moving it to the repo.

**Problem**: `.sops.yaml` has `path_regex: infra/config/secrets/.*\.enc\.yaml$` — SOPS refuses to encrypt any file whose path doesn't match this pattern. Files in `/tmp/` or any path outside the repo fail with "no matching creation rules".

**Solution**: Either: (a) create and encrypt the file in-place at the correct repo path, or (b) use `sops set` to edit an existing file. Never create secrets files in `/tmp/` and expect to encrypt them afterward.

**Rule**: SOPS `path_regex` is absolute-path matched. Always create new secrets files directly at their final repo path (`infra/config/secrets/`). Do not draft secrets in temp locations.

---
