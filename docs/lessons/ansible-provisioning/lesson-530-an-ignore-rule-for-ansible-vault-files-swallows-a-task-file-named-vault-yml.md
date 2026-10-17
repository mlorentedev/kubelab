---
id: lesson-530-an-ignore-rule-for-ansible-vault-files-swallows-a-task-file-named-vault-yml
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, git, gitignore, ci]
---

# An ignore rule for Ansible Vault files swallows a task file named `vault.yml`

**Context**: AI-009 PR 4a added a task file for the agent's vault clone hook,
`roles/agent_stack/tasks/vault.yml`, imported from the role's `main.yml`. Here
"vault" means the Obsidian knowledge vault, not Ansible Vault.

**Problem**: `infra/ansible/.gitignore` ignores `vault.yml` at any depth, under
"Secrets and sensitive files (CRITICAL - NEVER commit these)". `git add -A` skipped the
file without a word, and `git status` stayed clean. Every local signal was
green: the tests read the file from the worktree, and a live provision of ace2
ran it (`changed=2`, then `changed=0`). The commit, the rebase and the push all
went through without it. Only CI, from a clean checkout, failed with
`FileNotFoundError: .../tasks/vault.yml`.

**Solution**: Rename it to `vault_zone.yml`. The ignore rule stays, because it
protects real Ansible Vault files. `git check-ignore -v <path>` names the rule
that matched (`infra/ansible/.gitignore:22:vault.yml`).

**Rule**: When a new file never appears in `git status`, run
`git check-ignore -v` on it before anything else. Under `infra/ansible/`, never
name a file `vault.yml` or `vault.yaml`, whatever "vault" means in it. A green
local run proves nothing about a file git does not track, so a provision is
evidence only for what is committed.

**Tags**: `#gitignore` `#ai-009` `#pr-2102`
