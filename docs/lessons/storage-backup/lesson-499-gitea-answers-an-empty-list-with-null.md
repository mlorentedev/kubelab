---
id: lesson-499-gitea-answers-an-empty-list-with-null
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, gitea, restore-drill, api]
---

# Gitea answers an empty list with `null`: one empty repository made the restore drill unable to check anything

**Context**: BACKUP-040's restore drill (`make backup-drill-gitea`) reads live Gitea before it restores anything: every repository, and the branch count of each, so it can tell a complete restore from one that lost a repository. Any failure to read live is CANNOT CHECK, never a pass (lesson-416).

**Problem**: The first run on prod stopped at that read: `GET /repos/teledyne/openkm-brain/branches returned NoneType, expected a list`. That repository has never been pushed to. For a repository with no commits, Gitea 1.25.5 answers the branches endpoint with a JSON `null`, not `[]`. `GiteaClient._paginate` treated any non-list as a malformed answer and raised, so one empty repository stopped the drill from checking the other four. The restored server's API, read the same way inside the scratch container, would have failed in the same place.

**Solution**: Both readers treat a `null` page as an empty collection: `GiteaClient._paginate` and the drill's own paginator over `docker exec wget`. The drill's paginator now keeps a separate sentinel for a read that failed (non-zero exit, undecodable body), so `null` means "none" and only a real failure means CANNOT CHECK. Tests pin both: an empty repository live and restored passes, and a failed read of the restored server is CANNOT CHECK. The rerun passed with `teledyne/openkm-brain: 0 branch(es) restored, live 0`.

**Rule**: failing closed on an unexpected shape was the right default. It turned an API quirk into a loud CANNOT CHECK instead of a silent pass. But "empty" and "unreadable" are different answers, and a reader must keep them apart, because merging them either hides a failure or blocks every check. Learn the empty shape of an endpoint from the live server, with a resource that is really empty, not from the documentation or from a fixture that always has data.

**Tags**: `#gitea` `#restore-drill` `#issue-487`
