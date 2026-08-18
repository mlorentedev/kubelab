---
id: lesson-190-busybox-wget-lacks-http-method-support-use-sq
type: lesson
status: active
created: "2026-03-25"
owner: manu
tags: [kubelab, lesson]
---

# busybox wget lacks HTTP method support — use sqlite3 for DB operations

**Context**: Needed to rename a Gitea admin user from "admin" to "manu". Gitea has no `rename` CLI command. Tried using `wget --method=PATCH` to call the Gitea API from within the Alpine-based container.

**Problem**: Gitea's image is Alpine/busybox. busybox `wget` does not support `--method=PATCH`, `--body-data`, or custom HTTP methods. The migration would fail silently.

**Solution**: Use `sqlite3` directly on Gitea's SQLite DB (`/data/gitea/gitea.db`) for the rename operation. SQLite3 is available in Alpine. Direct DB update is simpler and has no API dependency.

**Rule**: In Alpine/busybox containers, don't assume full `wget`/`curl` capabilities. For SQLite-backed services (Gitea, Authelia, CrowdSec), direct DB operations via `sqlite3` CLI are more reliable than HTTP API calls from within the container. Always verify available tools in the target container image.
