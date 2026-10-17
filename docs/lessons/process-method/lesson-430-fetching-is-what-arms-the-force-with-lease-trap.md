---
id: lesson-430-fetching-is-what-arms-the-force-with-lease-trap
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: process-method
tags: [kubelab, process-method, git, force-push, parallel-sessions]
---

# Fetching is what arms the `--force-with-lease` trap

**Context**: Three agent sessions working the same repository in parallel, each
on its own branch, each force-pushing after rebases. `--force-with-lease` was the
habit, on the usual understanding that it is the safe force.

**Problem**: A plain `git push` was rejected as non-fast-forward. Someone had
merged `master` into my branch on the remote while I worked, and the rejection is
the only reason I looked. Had I reached for `--force-with-lease` — as I had
several times that afternoon — **it would have succeeded and silently discarded
that merge.**

The flag does not compare against the remote. It compares against your
**remote-tracking ref**, your local cache of the remote. So:

```
someone pushes to your branch      remote moves ahead
you `git fetch` (for any reason)   origin/<branch> now matches the remote
you `git push --force-with-lease`  lease satisfied — by the very commit
                                   it exists to protect against
```

**Fetching is what arms the trap.** Not an exotic sequence: fetching is the most
ordinary thing to do before a rebase, and every tool that shows branch status
does it for you. The window in which the lease protects you is the window in
which you have not looked at the remote — and it closes the moment you do
anything that touches it.

**Solution**: Look at what the lease would have accepted, before forcing.

```bash
git log origin/<branch> --oneline -3
```

That works precisely *because* it makes you read the commits. There is no flag
that substitutes for it: `--force-with-lease=<ref>:<sha>` with an explicitly
pinned SHA is the rigorous form, and nobody types it.

**Rule**: `--force-with-lease` protects against a remote you have not looked at.
It offers no protection against one you have fetched. In a repository where
anything else can push — a teammate, another agent session, a bot, a UI button —
read `origin/<branch>` before every force, and treat the flag as a seatbelt that
unbuckles when you check the mirror.

**The general form is the reason this is worth a lesson rather than a note**: it
is a guard whose safety property holds against the case you were not worried
about, and dissolves against the case you were. Using it correctly is what
disables it. That is a third shape distinct from
[[lesson-428]] (a check measuring the wrong sample) and from
[[lesson-429-the-state-that-was-evidence-became-residue-with-no-event]] (a correct
check whose output nobody read) — and it is the most dangerous of the three,
because the other two fail while you watch, and this one succeeds.

**The naming does real work in why nobody checks.** "With lease" sounds like a
claim about the remote. It is a claim about your local cache of the remote. A
guard that reads as stronger than it is will not be double-checked, and this one
is named for the reassurance rather than for the mechanism.

**Tags**: `#git` `#force-push` `#parallel-sessions` `#guards`
