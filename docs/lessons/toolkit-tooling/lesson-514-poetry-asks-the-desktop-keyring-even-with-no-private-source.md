---
id: lesson-514-poetry-asks-the-desktop-keyring-even-with-no-private-source
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, poetry, keyring, worktree-init]
---

# Poetry asks the desktop keyring even when no private source exists, and a locked keyring hangs the install with no output

**Context**: `make worktree-init` in a fresh worktree, 2026-10-01, from an agent session
with no interactive desktop prompt available.

**Problem**: `poetry install` stalled at 181 of 209 packages for 15 minutes. It printed
nothing and held no open socket, so it was not a slow download. This project declares no
private package source, so Poetry has no credential to fetch, yet it still queries the
desktop Secret Service. In a session where that keyring cannot be unlocked, the call
blocks indefinitely and nothing on screen says it is waiting for a keyring.

**Solution**: `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` on the three Poetry
calls in the `worktree-init` target (#1972). The same target then completed in 13 s in a
fresh worktree. The Makefile comment records why, and that the line must change if a
private source is ever added.

**Rule**: a package manager that stops with no output and no open socket is waiting on
something local, not on the network. Check the credential helpers before the index. Where
a project has no private source, give it the null keyring explicitly instead of letting
it inherit the desktop's.

**Tags**: `#poetry` `#keyring` `#worktree-init` `#pr-1972`
