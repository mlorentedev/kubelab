---
id: lesson-733-retiring-a-credential-path-moves-every-caller-that-borrowed-it
type: lesson
status: active
created: "2026-11-10"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, credentials]
---

# Retiring a credential path moves every caller that borrowed it, not only the ones it was named for

**Context**: #2578 moved `toolkit services gitea git` from the forge's break-glass admin password to the agents' authoring account (`dedalo`) and its token. The ticket named three commands: `gitea git`, `pr create` and `issue create`.

**Problem**: Two more callers depended on the same resolver and neither was named in the ticket. `gitea actions-secrets` built its client from `gitea_authoring.authoring_client`, which resolved through `resolve_git_credential`. Changing that function to the agent's token would have moved Actions-secret delivery to an account that cannot write a repository's secrets (repo-admin, #1781), and the failure would show up only on the next `--apply`. Three operator runbooks (offsite restore, GitHub retirement) ran `make gitea-git` for a mirror clone and a `push --mirror` across any repository. The agent account can do neither: it reads only the repositories that name it under `writers:`, and it cannot push to a protected default branch. The tests stayed green throughout. Nothing exercised the runbooks, and the actions-secrets tests monkeypatched the borrowed function away.

**Solution**: Before changing the resolver, list who calls it: `grep -rn` across `toolkit tests docs Makefile` for the function, its module and the make target. Each caller then gets an explicit credential of its own. `_actions_secrets_client` builds the superadmin basic-auth client the way `drop-empty` already does, and a test asserts its login is `manu`, not the agent. The runbooks use plain git over SSH as the operator (`git clone --mirror forge:<org>/<name>.git`, dotfiles#2512). That makes them the human path the wrapper's docstring always said humans should use.

**Rule**: A credential resolver shared "because it is the same credential today" is a coupling the next identity change has to unwind. When you retire or narrow one, enumerate its callers, including runbooks and make targets, which no test runs. Give each caller the credential its operation actually needs, and pin that choice in a test that names the login.

**Tags**: `#gitea` `#credentials` `#issue-2578`
