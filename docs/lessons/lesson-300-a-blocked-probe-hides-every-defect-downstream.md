---
id: lesson-300-a-blocked-probe-hides-every-defect-downstream
type: lesson
status: active
created: "2026-08-08"
owner: manu
tags: [kubelab, lesson, verification, probes, git, github-cli, shallow-clone, test-fixtures, ansible-033, gotcha]
---

# A blocked probe hides every defect downstream of where it stops (ANSIBLE-033)

**Context:** ANSIBLE-033's f2 probe — clone a private repo, commit, push, open a PR, all from a tmux session on ace2 under the dev-node PAT. It had one known blocker: the fixture, `go-dsa-sample`, was archived and therefore read-only.

**Problem:** Two defects, stacked, and the first made the second invisible.

The fixture was chosen for being *dormant*, so an acceptance branch could not collide with real work. That criterion turned out to select for archived repositories — dormant is what archiving produces. The push returned `403 This repository was archived`, which is indistinguishable from a permissions failure and sends you auditing the credential.

Replacing the fixture let the probe reach step 4 for the first time, where `gh pr create` aborted with *"you must first push the current branch to a remote"* — immediately after a `git push -u origin HEAD` that had returned 0. `git clone --depth 1` implies `--single-branch`, which pins the fetch refspec to the default branch. The push therefore writes `branch.<name>.remote` and `branch.<name>.merge`, but nothing can create `refs/remotes/origin/<branch>` because no refspec covers it. `@{upstream}` fails with *"not stored as a remote-tracking branch"*, and `gh` reads that as an unpushed branch. The `-u` had not lied about the config, only about the ref.

Both defects had been in the probe since it was written. The first one is why nobody knew about the second, and each round trip to discover one cost powering on an on-demand node.

**Solution:** A purpose-built private fixture (`kubelab-devnode-fixture`) rather than a borrowed one — of 41 private repos, 36 were archived and the other 5 were in active use, one of them the vault. Being permanent, it also turns post-rotation re-verification into a command instead of a manual step. For the PR, pass `--head` explicitly and skip the inference; widening the clone would trade away a real property of the probe for nothing. The corrected probe was then run end to end **from the workstation under the operator's own token** — enough to prove the flow, explicitly not enough to satisfy AC2, which needs the node and the dev-node PAT.

**Rule:** When a probe is blocked at step N, treat steps N+1 onward as **unverified, not working** — a green record above the blockage says nothing about what is below it. Where the environment is expensive to reach (an on-demand node, a physical device), buy down that cost first: run the probe against a local stand-in to shake out flow defects, then spend the real environment on the one axis the stand-in cannot exercise. And when picking a test fixture, state the property you actually need — *writable* — instead of a proxy like *dormant*, which quietly selected for the opposite.

**Tags:** `#verification` `#probes` `#git` `#github-cli` `#shallow-clone` `#test-fixtures` `#ansible-033` `#gotcha`
