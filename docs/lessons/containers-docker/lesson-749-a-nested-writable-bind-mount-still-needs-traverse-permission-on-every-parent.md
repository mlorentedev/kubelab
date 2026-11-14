---
id: lesson-749-a-nested-writable-bind-mount-still-needs-traverse-permission-on-every-parent
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, rootless-docker, bind-mounts, permissions]
---

# A nested writable bind mount still needs traverse permission on every parent

**Context**: Hermes's rootless sandbox mounts the whole vault read-only and the agent's zone read-write at a nested path. The gateway and sandbox run as container UID/GID 10000, mapped to host subuid/subgid 534287; the vault sync runs as the host agent user and enters that user namespace to read `0600` memory files.

**Problem**: The vault clone root was `0700` and owned by the sync user. Inside the sandbox it appeared as `root root`, so UID 10000 could not traverse it. The nested zone mount was present, writable, correctly owned and `0755`, yet creating a file still returned `Permission denied`. Making the zone or memories `01777` could not fix path traversal and had already mixed owners until atomic memory renames failed with `EPERM` (#3485).

**Solution**: Set the clone root to `0711`, which grants traverse without listing, and give the zone, memories and proposals one effective owner with mode `0755`. Preserve memory-file modes, including `0600`. Limit recursive ownership repair to the trees the gateway actually writes (`memories/` and `proposals/`), require measured drift, stop the gateway and running sandboxes first, use `follow: false`, and do not delete stopped sandbox workspaces. The regression tests pin the parent mode, positive path selection, repair guard, running-only cleanup and subordinate-range precondition. Live proof showed `10000:10000` inside the sandbox and `534287:534287` on the host, followed by two `changed=0` provisions.

**Rule**: A writable bind mount does not bypass permissions on its parents. Grant the least permission needed for traversal, then scope ownership repair to intended writable trees rather than every file below the mount. Never respond to a nested-mount `EACCES` with `0777` or a zone-wide recursive chown.

**Tags**: `#docker` `#rootless-docker` `#issue-3485`
