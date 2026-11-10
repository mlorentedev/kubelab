---
id: lesson-728-gitea-repository-creation-limit-is-write-only-and-checked-on-the-owner
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, auth-024]
---

# Gitea's repository creation limit is write-only and is checked on the owner, so it converges by marker and leaves organization repositories alone

**Context**: AUTH-024 (#3148) had to stop the forge's machine accounts from
creating repositories under their own name or forking, without touching the
organization repositories they are collaborators on.

**Problem**: Two facts about Gitea 1.27.3 shaped the fix. `CanCreateRepoIn`
checks `max_repo_creation` on the repository's *owner*, so a limit of 0 on a
user blocks its own repositories and its forks but not a repository created in
an organization. And the field is in `EditUserOption` but absent from
`api.User`: a PATCH sets it and no read returns it, so the bootstrap cannot
converge by comparison as it does for `prohibit_login`. The PATCH also requires
`login_name` and `source_id`, or Gitea refuses it.

**Solution**: `gitea-bootstrap.sh` writes `max_repo_creation: 0` once per
machine account and records it in `/data/gitea/.kubelab-creation-limit-<login>`
only after the PATCH returned 0 (`set -eu` exits before the marker on a
failure). A recorded account logs neither "Created" nor "Updated", so the
role's `changed_when` stays quiet. `tests/test_gitea_machine_creation_limit.py`
covers first write, converged run and failed write; a mutation of the value to
-1 turns it red.

**Rule**: Before converging a Gitea field, check that `api.User` (or the
matching read type) returns it. A field you can only write converges by a
marker written after a successful write, never by comparison and never
unconditionally.

**Tags**: `#gitea` `#auth-024` `#issue-3148`
