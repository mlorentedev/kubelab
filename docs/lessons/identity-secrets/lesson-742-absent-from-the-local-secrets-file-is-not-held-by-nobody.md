---
id: lesson-742-absent-from-the-local-secrets-file-is-not-held-by-nobody
type: lesson
status: active
created: "2026-11-13"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, ansible, sops, concurrency]
---

# A key missing from the local secrets file does not mean nobody holds the value

**Context**: lesson-684 added a recovery step to the `beelink_services` role. Before minting, it revokes every named Gitea token whose SOPS key is empty. The reasoning was that such a token has no consumer, because nobody holds its value.

**Problem**: The role reads SOPS from the controller's working copy, and two checkouts on one machine can each run a provision. On 2026-11-13 at 03:13Z, a provision from the main checkout minted `kubelab-repo-reader` and recorded it there, not yet committed. Ten minutes later a provision from another worktree, whose `prod.enc.yaml` lacked the key, revoked that token and minted a new one. Both runs ended `failed=0`. Nothing marked the first value as dead, and a later run from the first checkout would have read it as recorded and never repaired it.

**Solution**: The revoke is no longer the default (#3428). The role lists, from Gitea, the unrecorded names it holds. When it holds any, the play stops with ERROR/WHY/FIX. The revoke runs only for those names, and only with `EXTRA='gitea_revoke_unrecorded_tokens=true'`, which is the lesson-684 case of a value lost after a failed record. `tests/test_gitea_token_mint_convergence.py` pins the order (probe, refusal, revoke), the default-off flag, and that the revoke touches only names the probe found.

**Rule**: Never take an irreversible action on the strength of an absence in a local copy of shared state. A working tree, a cache or an unmerged branch can each lack what another copy holds. Make the action a stop that names its evidence, and let the operator confirm it.

**Tags**: `#gitea` `#sops` `#issue-3428` `#lesson-684`
