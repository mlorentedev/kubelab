---
id: lesson-424-a-convergence-step-scoped-to-the-creation-diff-repairs-nothing
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, reconciler, idempotence, gitea, guards]
---

# A convergence step scoped to the creation diff never repairs what already exists

**Context**: The Gitea reconciler's `reconcilers` team granted `repo.code -> write`
over zero repositories, because `includes_all_repositories` defaults to `false`.
#1611 fixed it: `create_team` sends the flag, `edit_team` widens a team that
predates it, and `ensure_team` refuses a team still missing it. Tests, mutation,
review, green CI, merged.

**Problem**: Measured on prod immediately after the merge, nothing had changed.

```
personal/reconcilers   includes_all_repositories=False   repos attached: NONE
teledyne/reconcilers   includes_all_repositories=False   repos attached: NONE
hefesto on personal/resume: read      teledyne/fae-brain: read
```

`execute` ran `ensure_team` over `receiving`, which is
`{repos_to_create} | {repos_to_migrate}`. Every declared repository already
existed, so the set was empty — and the CLI returns at `plan.is_noop` before
`execute` is called at all. The repair was correct and unreachable.

The shape generalises past this bug. **A reconciler's convergence steps get
attached to the thing being created, because that is when they were first
needed.** `ensure_team` exists so a newly created repository has somewhere to
live, so it was iterated over new repositories. But the grant belongs to the
ORGANIZATION, and organizations outlive the moment something was created in them.
Any property of a long-lived object, repaired only while creating a short-lived
one, is repaired exactly once and then never again.

**Solution**: Plan over the DECLARED state, not the created state, and let one
predicate answer for both halves.

```python
def team_needs_convergence(team: Mapping[str, Any] | None) -> bool: ...

# plan_reconcile: is there work?
teams_to_converge = tuple(sorted(o for o in declared_orgs if team_needs_convergence(existing_teams[o])))

# execute: reachable without a creation
for org in sorted((receiving | set(plan.teams_to_converge)) - failed_orgs):
```

Two details that are not incidental:

- **`is_noop` must count it.** The CLI returns early on a no-op plan, so a repair
  the plan does not mention is a repair `execute` is never asked to make. The rule
  written into the property: *anything `execute` acts on belongs in `is_noop`;
  anything report-only does not.* That is what separates `teams_to_converge` from
  `visibility_drift`, which look identical — both a live value disagreeing with
  the declaration — and are opposites.
- **The predicate covers every field the repair sends**, not the one that was
  wrong. A subset lets the plan report a match on a team `ensure_team` would
  refuse: the same defect one field over.

**Rule**: When a reconciler repairs a property, ask *what owns that property* and
iterate THAT, not the diff that made you notice. If the answer is "an
organization", "a cluster", "a node" — anything that exists between runs — then
scoping the repair to a creation means it runs on the first run and never again,
and every subsequent run reports a converged system.

The tell: a repair reachable only inside an `if` that tests whether something is
being CREATED. Ask what happens on a system where everything already exists —
which is what every system becomes.

Verified by consequence rather than by the success message: after `--apply`, the
bot's push to `personal/resume` went from `User permission denied for writing` to
creating the ref. See [[lesson-425-a-capability-probe-can-stop-at-the-first-authorization-layer]]
for why that probe, and not the API's own permission field, is what settled it.

**Tags**: `#reconciler` `#idempotence` `#gitea` `#tool-035` `#pr-1616`
