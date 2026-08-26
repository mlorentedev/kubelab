---
id: lesson-398-a-quoting-bug-that-widens-a-scope-does-not-announce-itself
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, ansible, gitea, least-privilege]
---

# A quoting bug that breaks a command announces itself; one that widens a scope does not

**Context**: AUTH-004 C5 (#1013). An Ansible task mints a scoped API token for a
machine account, written as a string command:

```yaml
command: >-
  docker exec gitea su git -c
  "gitea admin user generate-access-token --username {{ gitea_bot_user }}
   --token-name kubelab-provisioning --scopes {{ gitea_bot_scopes }} --raw"
```

**Problem**: The task failed. `no_log: true` hid the reason, and the same
pipeline typed by hand against the container returned exit 0 — so the fault was
in the invocation, not the command. YAML folding collapsed the block and argv
splitting then stripped the inner quoting, leaving `su` to read `gitea` as the
command and `admin user generate-access-token …` as positional arguments.

**That much is ordinary. What made it worth a lesson was the wreckage.** Listing
the account's tokens afterwards showed one that nobody had asked for:

```
"id":1  "name":"gitea-admin"
```

`gitea-admin` is `generate-access-token`'s **default** token name, and its
default `--scopes` is **`all`**. A partial invocation had reached the binary with
the flags gone and minted a token with every scope — on an account whose entire
purpose is least privilege — while the play reported **failure** and the operator
held no token at all.

So the failure mode is inverted from the usual one. A quoting bug that breaks the
command shows up as a red task and gets fixed. This one produced a red task
*and* a silent over-privileged credential, and only the red half was visible. The
account had two live tokens before anyone counted.

**Solution**: `argv:` — the list form, passed verbatim, with no YAML folding and
no re-parsing:

```yaml
command:
  argv: [docker, exec, gitea, su, git, -c, "gitea admin user generate-access-token …"]
```

Both tokens were revoked (`HTTP 204`, list empty) before re-running, so the play
minted into a clean slate. A test asserts the `argv` form **and** that
`--token-name`, `--scopes` and `--raw` are all present, because their absence is
what silently selects the permissive defaults.

**Rule**: Any command that mints a credential goes through `argv:`, never a
string — the cost of being wrong is not a failed task, it is a credential you did
not intend to exist. And when a minting task fails, **enumerate the credentials
before retrying**: a tool that defaults its own flags will have created something
even though the wrapper reported failure. `--scopes` defaulting to `all` and
`--token-name` defaulting to a fixed string are the two that bit here, and a
fixed default name means the *second* attempt then fails on a duplicate, which
reads like the same bug and is not.

**Tags**: `#ansible` `#gitea` `#least-privilege` `#quoting` `#pr-1437`
