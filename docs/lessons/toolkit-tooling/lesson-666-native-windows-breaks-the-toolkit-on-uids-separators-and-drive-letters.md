---
id: lesson-666-native-windows-breaks-the-toolkit-on-uids-separators-and-drive-letters
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, windows]
---

# Native Windows breaks the toolkit on uids, path separators and drive letters, not only on encodings

**Context**: Clearing the Windows baseline before the Headscale upgrade work (VPN-ACL-006).
On native Windows (PowerShell, or Git Bash, which still runs Windows Python), 19 Headscale
tests and 21 app-drill tests failed. Both restore drills and the Argo CD RBAC evaluator
could not start a container at all.

**Problem**: lesson-289 covers the encoding half, and it recurred here: `read_text()`
decoded UTF-8 sources with cp1252. Three other defects had nothing to do with encoding:

- `docker run --user f"{os.getuid()}:{os.getgid()}"` raises `AttributeError`, because
  Windows has no `os.getuid`. Three production call sites did this.
- A scan built `str(path.relative_to(root))` and matched it against `roles/x/`. On Windows
  the string holds backslashes. One guard then reported a false second owner, and another
  found nothing to check.
- A fake parsed a bind mount with `mount.split(":")[0]`, which returns `C` for
  `C:\...:/run/drill:ro`.

**Solution**: `toolkit.core.io.docker_user_args()` returns `["--user", "uid:gid"]` where the
host has uids and `[]` where it has none. Docker Desktop bind mounts carry no uid ownership
to match. Scans now compare `as_posix()` paths, mounts are parsed with `removesuffix` on the
container side, and reads pass `encoding="utf-8"`. The `0600` assertion now runs only on
POSIX. On Windows, a test checks the property that still holds there instead: the key's
directory is under the per-user temp dir (#2820, #2826).

**Rule**: Do not reach for `os.getuid`, `str(path)` comparisons or `split(":")` on a path in
code a Windows workstation may run. Use `docker_user_args()`, `as_posix()` and a split anchored
on the known suffix. When a guard stops holding on one OS, test the property that does hold
there. Skipping the guard silently is not a replacement.

**Tags**: `#windows` `#portability` `#docker` `#pr-2820` `#pr-2826`
