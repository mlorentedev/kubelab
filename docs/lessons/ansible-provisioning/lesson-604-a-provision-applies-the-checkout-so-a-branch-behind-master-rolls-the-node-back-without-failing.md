---
id: lesson-604-a-provision-applies-the-checkout-so-a-branch-behind-master-rolls-the-node-back-without-failing
type: lesson
status: active
created: "2026-10-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, provision, worktrees]
---

# A provision applies the checkout, so a branch behind master rolls the node back without failing

**Context**: `make provision NODE=bee ENV=prod TAGS=gitea` was run three times on 2026-10-17 from a branch cut before #2425, which had moved the Beelink runner to `gitea/runner:4.1.0`.

**Problem**: Ansible renders what the checkout declares, so each run put `gitea/act_runner:0.2.13` back and recreated the container, which can cut a running job. Nothing failed, no check ran, and it was found from a message by a peer session. A handoff note saying "do not provision bee" had existed and did not stop it (lesson-365: a reminder fails when the situation arrives).

**Solution**: `make provision` now passes `--require-fresh` to `toolkit infra ansible run`, which asks git whether `origin/master` changed anything under `infra/ansible` or `infra/config/values`, or the inventory generator, since this checkout last merged it (`git diff HEAD...origin/master`, three dots: the master side of the merge base). If so it stops before generating the inventory and names the files, the cause and the way out. `FORCE=1` overrides; `FORCE=0` does not. `--check` is not refused, since it changes nothing, and a checkout that cannot be compared (no network, no git) is refused too. `tests/test_provision_requires_fresh_checkout.py` builds real repositories for the range semantics and `make mutate` turned it red for the two-dot range, a disabled guard, a `FORCE=0` that overrides and a fail-open comparison.

**Rule**: A tool that applies a declaration must check the declaration is current before it applies it, not rely on whoever runs it remembering which branch they are on. Pick the paths coarsely (everything Ansible renders) rather than computing which roles a playbook uses: a refusal that costs one `git merge` is cheaper than a rollback that costs a job. Other targets that render roles (`make deploy`) do not pass the flag yet.

**Tags**: `#provision` `#stale-branch` `#ops-041` `#pr-2441`
