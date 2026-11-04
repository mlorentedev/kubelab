---
id: lesson-704-gitea-permission-endpoint-misses-team-units
type: lesson
status: active
created: "2026-11-03"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, auth-022]
---

# Gitea's collaborator permission endpoint answers `read` for an account a team grants write to

**Context**: AUTH-022 (#2577) makes the agents' account a collaborator at `write` on each repository that declares it. The reconciler needs to read whether the grant already holds, so `GET /repos/{o}/{r}/collaborators/{u}/permission` was measured first against `personal/imagesensortool` on prod.

**Problem**: The endpoint answered `read` for `hefesto`, which the `reconcilers` team grants write on every unit. It also answered `read` for `mentor`, who is in no write team, and `owner` for `manu`. So it reports the coarse access mode, and on a repository readable by every signed-in account (`REQUIRE_SIGNIN_VIEW`, `private: false`) the floor is `read`. An account with no grant at all reads the same as one with a team grant on units.

**Solution**: Read the grant from two calls: `GET .../collaborators/{u}` (204 means a collaborator row exists, 404 means none) and the permission endpoint for the row's mode. `collaborator_needs_grant` in `toolkit/features/gitea_repos.py` needs both, and `ensure_collaborator` uses the same predicate on its read-back.

**Rule**: Do not take a Gitea access mode as proof that a grant exists. A public repository and unit-based teams both make `read` mean several different things. Read the object that is the grant itself (the collaborator row, the team and its members), and use the mode only for the level of a grant you already know is there.

**Tags**: `#gitea` `#auth-022`
