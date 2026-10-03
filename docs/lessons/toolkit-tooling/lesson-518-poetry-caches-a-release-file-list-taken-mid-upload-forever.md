---
id: lesson-518-poetry-caches-a-release-file-list-taken-mid-upload-forever
type: lesson
status: active
created: "2026-10-03"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, poetry, pypi, cache, worktree-init]
---

# Poetry caches a release's file list forever, so a lock taken during the upload misses wheels for good

**Context**: `make worktree-init` in a new sibling worktree, 2026-10-03. `poetry.lock` is
gitignored here, so every worktree resolves its own lock.

**Problem**: the install failed with `Unable to find installation candidates for
setproctitle (1.3.8)`: 16 wheels identified, all skipped for their ABI tags. The
generated lock listed only cp310 and cp311 wheels, with no cp312 wheel and no sdist.
PyPI lists 100 files for that release. Poetry's metadata cache entry for
`setproctitle 1.3.8` (2.9 KB) was written on 2026-10-01 at 21:00:11Z, and PyPI shows
the release's files uploaded between 20:58:13Z and 21:09:27Z. The cache captured the
file list mid-upload, and the entry's expiry field is `9999999999`, so every later
`poetry lock` on this machine reused the partial list. The error suggests regenerating
the lock with `--no-cache`. It does not say that the cache is the cause.

**Solution**: `poetry cache clear PyPI:setproctitle:1.3.8 -n`, which removes only that
entry, then `make worktree-init` again. The new entry is 17 KB, the lock lists all 100
files, and `toolkit` imports.

**Rule**: when a lock resolves a version but finds no installable artifact for an
interpreter the release supports, compare the cached file list with the index before
suspecting the environment. A release resolved in its first minutes can be cached
incomplete for good. Clear that one entry, not the whole cache.

**Tags**: `#poetry` `#pypi` `#cache` `#worktree-init`
