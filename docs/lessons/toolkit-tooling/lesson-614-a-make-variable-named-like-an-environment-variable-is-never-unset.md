---
id: lesson-614-a-make-variable-named-like-an-environment-variable-is-never-unset
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, make, identity]
---

# A Make variable named like an environment variable is never unset

**Context**: #909 added `make credentials-reset-password`, which resets one Authelia
login. The natural spelling was `USER=operator`.

**Problem**: Make imports the environment as variables, so `$(USER)` is never empty:
when the caller does not set it, it is the shell's login. Here that is the OS user
(`networking.ssh_users.homelab`), which is not the app identity and only coincides
with one by accident (SSOT-014). A reset run without `USER=` would have resolved a
real account the caller never named, and written its password. The same expansion
also bites the other way: `make mutate FROM='--identity "$(IDENTITY)"'` hands the
recipe `--identity ""`, because Make expands `$(...)` inside a command-line value,
so the mutation matched nothing.

**Solution**: the variable is `IDENTITY=`, which no shell sets, and the recipe
quotes it (`--identity "$(IDENTITY)"`) so an unset value reaches the CLI as an empty
string, which it refuses with the valid keys, instead of `--identity --env prod`
swallowing the next flag. `tests/test_credentials_reset_password.py` asserts both
and fails if the block ever reads `$(USER)`. In `make mutate`, write a literal `$`
as `$$`.

**Rule**: never name a Make variable after one the shell exports (`USER`, `HOME`,
`PATH`, `SHELL`, `PWD`, `LANG`): it cannot be unset, so "not given" becomes "the
environment's value". Quote every optional variable a recipe passes to a flag.

**Tags**: `#make` `#identity` `#issue-909`
