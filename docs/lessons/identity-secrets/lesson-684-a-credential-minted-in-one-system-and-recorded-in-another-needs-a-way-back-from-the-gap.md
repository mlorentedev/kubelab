---
id: lesson-684-a-credential-minted-in-one-system-and-recorded-in-another-needs-a-way-back-from-the-gap
type: lesson
status: active
title: "A credential minted in one system and recorded in another needs a way back from the gap between them"
created: "2026-11-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, ansible, sops, idempotence]
---

# A credential minted in one system and recorded in another needs a way back from the gap between them

**Context**: The `beelink_services` role creates five Gitea access tokens. Each is two tasks: `generate-access-token` in the container, then `toolkit secrets set` on the controller, which writes SOPS. Both are gated on the SOPS key being empty, so a converged host mints nothing.

**Problem**: On 2026-11-01 the first prod run after #2897 minted `kubelab-issue-reader`, then failed to record it. The controller's worktree kept its Poetry venv in the cache directory, and the record task runs `<repo>/.venv/bin/toolkit`. The token now existed in Gitea. Its value was gone, because the mint is `no_log` and its register died with the play. SOPS still had no key, so the gate stayed open. The next run would mint the same name, Gitea refuses a second token with one name, and the role could never converge without a manual delete on the node. The gate was idempotent only on the happy path: it read one system to decide about two.

**Solution**: Before any mint, the role asserts the controller's toolkit is executable, so it never mints what it cannot record. It also revokes, through the API, every named token whose SOPS key is empty. Such a token has no consumer, since nobody holds its value, so deleting it is safe, and it frees the name. A 404 means there was nothing to revoke. The admin password probe and reassert moved ahead of the revoke, because Gitea's token endpoints take Basic Auth only. `make worktree-init` now forces an in-project venv. Setting `POETRY_VIRTUALENVS_IN_PROJECT` was not enough: the setting governs only where Poetry creates a venv, and Poetry reuses a cache venv it already has for the project whatever the setting says. The first checkout after the merge proved it, ending with no `.venv/bin/toolkit`. So the target also sets aside a venv that resolves anywhere but the worktree and rebuilds it there. A test with a fake `poetry` could not see this, because the fake has no cache. `tests/test_gitea_token_mint_convergence.py` derives the token names from the mint tasks and fails if one is not revoked first. It also fails if the revoke can touch a recorded token, or if the preflight comes after a mint.

**Rule**: When a write spans two systems and the second can fail after the first succeeded, the gate must handle the half-done state as well as the done and not-done ones. Either check that the second write can succeed before the first, or make the first undoable from the state the failure leaves behind. Usually do both.

**Tags**: `#gitea` `#sops` `#idempotence` `#issue-2902`
