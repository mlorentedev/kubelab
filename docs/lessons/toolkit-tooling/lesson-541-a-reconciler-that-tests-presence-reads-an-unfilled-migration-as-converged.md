---
id: lesson-541-a-reconciler-that-tests-presence-reads-an-unfilled-migration-as-converged
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, gitea, reconciler, migration]
---

# A reconciler that tests presence reads an unfilled migration as converged

**Context**: `make gitea-reconcile` plans a migration for a declared repository with a
`migrate_from` source only when the repository is ABSENT. TOOL-035's first PR had created the
declared repositories as empty shells, and `POST /repos/migrate` answers 409 on an existing
target. `resume` and `fae-brain` were dropped and migrated. `teledyne/openkm-brain` never was.

**Problem**: From 2026-09-02 to 2026-10-08 the reconciler printed "forge matches the
declaration" over a repository holding 0 git objects. The repository existed, so it was in
neither the create nor the migrate list, and an empty plan reads as convergence. Its code, 18
issues and 17 pull requests lived only on GitHub, while Gitea was meant to be its only home.
BACKUP-040's restore drill showed it with 0 branches on 2026-10-01 and
was read as a JSON quirk (lesson-499). Then a second defect showed behind the first:
`drop-empty`, the repair, checked Gitea's `empty` field, which covers git only, and would have
deleted the 2 issues created in Gitea since (#2133).

**Solution**: The plan now carries `unfilled_migrations`: declared with a source, present, and
`empty: true`. It is reported and never acted on, and the CLI exits 1 naming the repair.
`drop-empty` counts issues and pull requests in every state through the basic-auth session and
refuses unless the operator passes that exact count. Proven live on prod: `make gitea-reconcile`
went from exit 0 to exit 1 on the same forge, and `make gitea-drop-empty
REPO=teledyne/openkm-brain` printed `issues+pulls=2` and refused.

**Rule**: When a reconciler's action is "bring X into existence with content", its convergence
test must read the content, not the existence. A precondition that only the first run can
satisfy (absent, so migrate) leaves every later run blind to a first run that half-happened.
And a field named `empty` answers for the layer that set it: before deleting on it, list what
else the object owns.

**Tags**: `#gitea` `#reconciler` `#issue-2133`
