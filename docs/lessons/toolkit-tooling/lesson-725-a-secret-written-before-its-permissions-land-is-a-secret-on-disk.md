---
id: lesson-725-a-secret-written-before-its-permissions-land-is-a-secret-on-disk
type: lesson
status: active
created: "2026-11-07"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, secrets, windows, fail-closed]
---

# A secret written before its permissions land is a secret on disk, and a failed hardening leaves it there

**Context**: `write_owner_only` in `toolkit/features/headscale_authkey.py`
delivers a minted Headscale pre-auth key to a file that must be readable only
by its owner. On POSIX the mode is passed to `os.open` and the kernel applies it
atomically; on Windows mode bits are meaningless and the ACL is rewritten by a
**separate** `icacls` call.

**Problem**: The Windows branch created the file, wrote the key, closed it, and
*then* hardened it (`#3196`). That is two defects in one ordering. First, the
file carried the inherited directory DACL for as long as the key had been in it
— the docstring called it "a short create-to-ACL window that is documented
rather than hidden", which is a description of the hole rather than a fix.
Second, and worse, `icacls` ran with `check=True`, so a failure raised
`CalledProcessError` **after** the secret was on disk and nothing removed it: the
operator saw a traceback, the file stayed readable, and the exception was the
only evidence it existed. `#3196` was filed for the cleanup alone and the window
turned out to be the same bug.

**Solution**: Create empty, harden, then write — and unlink on any failure after
the create. An empty file has nothing to leak, so the window closes without a
temp-file-plus-rename dance (which does not close it, it moves it to the temp
name). Three details are not obvious and each one is a real failure:

- `subprocess.CalledProcessError` is **not** an `OSError` — it derives from
  `SubprocessError` → `Exception`. A cleanup handler catching only `OSError`
  misses the exact failure this lesson is about. Catch
  `(OSError, subprocess.SubprocessError)`.
- `os.close` must precede `unlink`. Windows refuses to unlink a file it still
  holds open, so cleanup ordered the other way raises inside the `finally` and
  masks the original error.
- The error the operator sees has to name the **key id**, because by then the key
  exists on the VPS whatever happened to the file. `write_owner_only` does not
  know the id, so `mint` wraps the delivery call and appends it. "Could not write
  the file" is the message that leaves a live pre-auth key behind
  (the same shape as `lesson-724`).

Proven by three tests: the file is empty at the moment the hardening call runs,
an ACL failure unlinks it and names the key, and a write failure unlinks it too.

**Rule**: Wherever permissioning is a step *after* creation rather than an
argument to it, the order is **create empty → harden → write**, and every
failure after the create unlinks. A secret is only as protected as the file's
state at the instant the permission step runs, and a security step that raises
without cleaning up has not failed closed — it has failed while leaving the
artifact behind. Before trusting a "documented" window, ask what the file
contains during it.

**Tags**: `#secrets` `#windows` `#fail-closed` `#3196`
