---
id: lesson-619-a-reconciler-run-from-a-worktree-reconciles-that-worktrees-declaration
type: lesson
status: active
created: "2026-10-22"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, branch-protection, worktrees]
---

# A reconciler run from a worktree reconciles that worktree's declaration, not master's

**Context**: #2643 added `deploy-shape` to `ci.branch_protection` in `common.yaml`, and it merged.
The live reconcile is `make branch-protection-apply`, run by the operator.

**Problem**: The operator ran it in a feature worktree whose branch predated #2643. It read that
checkout's `common.yaml`, compared the live protection against a declaration without
`deploy-shape`, and printed `[SUCCESS] mlorentedev/kubelab@master: already matches the
declaration`. That line is true for the declaration it read, so a stale checkout yields a success
message and no error. `make branch-protection-check` run from a checkout at `origin/master` showed
the real drift: live had four contexts, master declared five.

**Solution**: Run the reconcile from a checkout of `origin/master`
(`git checkout --detach origin/master`), then re-read the live object:
`gh api repos/mlorentedev/kubelab/branches/master/protection/required_status_checks --jq '{contexts, checks}'`
(`checks` carries each context's `app_id` pin, which `contexts` does not show).

**Rule**: A reconciler applies the declaration in the tree it runs from. Before you apply live state
from a merged change, check that the checkout contains that change (`git merge-base --is-ancestor
<merge-sha> HEAD`). Then verify the outcome by reading the remote object, never from the
reconciler's summary line.

**Tags**: `#branch-protection` `#pr-2643` `#delivery-004`
