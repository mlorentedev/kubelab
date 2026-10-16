---
id: lesson-577-a-path-the-sync-user-cannot-read-fails-the-whole-add-and-an-exclude-pathspec-hides-it
type: lesson
status: active
created: "2026-10-15"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, hermes, git, rootless, ai-012]
---

# One file the sync user cannot read stops the zone syncing, and an exclude pathspec reports success while staging nothing

**Context**: AI-012 PR 4b mounted the vault zone's `memories/` over the gateway's `memories/`, so the existing host sync would commit what the agent remembers. The gateway runs in rootless Docker: its `hermes` user is subuid 534287 on the host, and the sync runs as the host user `hermes-kubelab`.

**Problem**: Hermes writes `MEMORY.md.lock` and `.mem_*` temporaries `0600` as that subuid. `git add --all` fails the whole command on one unreadable file, so `hermes-kubelab-vault-sync` stopped committing the zone, session record included, and paged. The first fix, `:(exclude,glob)**/*.lock` pathspecs, looked right: the unit exited 0 and the same `git add -n` listed the files from an interactive shell. Under the unit's environment (`GIT_CONFIG_GLOBAL=/dev/null`) it staged nothing, exit 0, on git 2.43, repeatedly; `git diff --cached --quiet` then passed and the script exited without a commit. A unit test on a developer's git passed too.

**Solution**: Skip the files with a root-owned ignore file passed as configuration, like the hooks: `-c core.excludesFile=/usr/local/libexec/agent-stack/vault-ignore` (`*.lock`, `.mem_*`), and a plain `git add --all -- ":(top,literal)$zone/"`. Proof on ace2: one forced sync committed `memories/MEMORY.md` and `USER.md` as `hermes-kubelab` and pushed, with the lock files left untracked.

**Aftershock**: the ignore file names the two artifacts seen, not the cause. A check that replaced `MEMORY.md` the way an atomic write does (`mkstemp` then `os.replace`) left it `0600`, and the sync failed on a name the file did not exclude; Hermes's own writes arrive `0644`, which is why the live run was clean. The next unreadable name fails the unit the same way, loudly, until it is added.

**Rule**: A directory a different uid writes into will contain files the reader cannot open; decide what the reader skips, in a file the writer cannot edit, before mounting it. And never accept "exit 0 and nothing happened" from a staging step: prove it by the commit it should have produced, under the same environment the unit runs in, because a second environment variable was enough to change the answer.

**Tags**: `#hermes` `#git` `#rootless` `#ai-012`
