---
id: lesson-298-when-you-cannot-own-the-file-verify-it-a-guar
type: lesson
status: active
created: "2026-08-08"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# When you cannot own the file, verify it — a guarded write is not a fallback (ANSIBLE-033)

**Context:** The `dev_node` role ran `gh auth setup-git` so one PAT would serve both `gh` and git-over-HTTPS. Follows directly from the ANSIBLE-028 one-writer-per-file lesson above.

**Problem:** `gh auth setup-git` writes `~/.gitconfig` — a file the dotfiles bootstrap, run *earlier in the same role*, redeploys wholesale every pass. The task looked harmless because it never fired: the helper was always already present, so the idempotence guard skipped it. Deleting the helper by hand and re-provisioning revealed why — the bootstrap restored it **mid-run**, before the role's own check executed. So the role can never durably write that file at all, and in the one scenario where the task would have fired (dotfiles dropping the helper), it would have churned forever: bootstrap wipes, `setup-git` rewrites, `changed` every pass. The "guarded fallback" was a churn generator wearing a safety guard.

**Solution:** Split ownership by concern. The token is the role's; the credential helper is dotfiles'. The role asserts the wiring and fails loudly with a message naming the owner, instead of writing a file it does not own. The `~/.gitconfig.local` seam alternative was rejected: no such seam exists, and creating one is a change to the dotfiles repo (the `dotfiles#788` precedent), not to this one.

**Rule:** One-writer-per-file has a second half nobody states: when the file's owner is someone else, the answer is **verify, don't write** — assert the contract and fail loudly, naming who owns it. Also: a task that never fires is not automatically safe. Test the branch you think is dead, because "it always skips" and "it would churn if it ran" look identical from a green pipeline.

**Tags:** `#ansible` `#idempotence` `#config-ownership` `#dotfiles` `#ansible-033` `#gotcha`
