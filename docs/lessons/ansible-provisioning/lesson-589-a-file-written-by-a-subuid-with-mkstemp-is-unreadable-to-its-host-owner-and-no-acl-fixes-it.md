---
id: lesson-589-a-file-written-by-a-subuid-with-mkstemp-is-unreadable-to-its-host-owner-and-no-acl-fixes-it
type: lesson
status: active
title: "A file written by a subuid with mkstemp is unreadable to its host owner, and no ACL fixes it"
created: "2026-10-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, rootless-docker, permissions, hermes]
---

# A file written by a subuid with mkstemp is unreadable to its host owner, and no ACL fixes it

**Context**: hermes-kubelab's gateway runs under rootless Docker and writes its memories into a directory the host user (uid 999) syncs to the vault with `git add`.

**Problem**: Hermes saves `MEMORY.md` with `mkstemp` (0600, umask-independent) and renames it over the old file; a rename keeps the mode. The result is `-rw------- 534287:534287`, a host subuid the owner of the daemon cannot read. One unreadable file fails the whole `git add`, so `hermes-kubelab-vault-sync.service` failed every 15 minutes from 2026-10-17 10:15Z and `OnFailure` paged the operator each time (#2417). The role's own comment assumed the final memory files stayed readable; that held only for files Hermes had not rewritten (`USER.md` was still 0644). The same mechanism had failed the unit once on 2026-10-15 and recovered by accident.

**Solution**: The sync re-executes itself inside the user namespace of the rootless daemon (`nsenter --user --target $(cat .../dockerd-rootless/child_pid)`). That namespace belongs to the sync user, root there is that user on the host, and the subuids are mapped into it, so the files are readable and the host gains nothing. `tests/test_hermes_vault_sync.py` covers entering once, never in a loop, and failing (not syncing from the host) when the daemon is down.

**Rule**: Nothing applied at creation time fixes a 0600 file written by another uid: a default ACL is masked to `---` and umask is ignored by `mkstemp`. Either fix the mode after creation and before the read (which races the writer), or read from the namespace that maps the writer. A comment that says a file "stays readable" is a claim about the writer; test it against the writer.

**Tags**: `#rootless-docker` `#permissions` `#pr-2417`
