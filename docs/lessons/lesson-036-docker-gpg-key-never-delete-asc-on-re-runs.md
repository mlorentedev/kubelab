---
id: lesson-036-docker-gpg-key-never-delete-asc-on-re-runs
type: lesson
status: active
created: "2026-03-19"
owner: manu
tags: [kubelab, lesson]
---

# Docker GPG key: never delete .asc on re-runs

**Context**: Docker role migrated from deprecated `apt_key` (.gpg) to `get_url` (.asc). Role deleted BOTH .gpg and .asc on every run, then re-downloaded .asc.

**Problem**: Delete-and-recreate cycle leaves apt in inconsistent state. `apt_repository` sees conflicting Signed-By values (ghost .gpg reference in cached source vs new .asc). Fails with `E:Conflicting values set for option Signed-By`.

**Solution**: Only delete legacy .gpg (and .gpg~ backup). Leave .asc untouched. Only clean source files when migrating (`.gpg` was changed → old sources need cleanup). `get_url` is naturally idempotent — doesn't re-download if file exists.

**Rule**: When migrating key formats, only remove the OLD format. Never delete-and-recreate the current format — it breaks idempotency.
