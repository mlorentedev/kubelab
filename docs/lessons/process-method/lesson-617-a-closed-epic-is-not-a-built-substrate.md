---
id: lesson-617-a-closed-epic-is-not-a-built-substrate
type: lesson
status: active
created: "2026-10-22"
owner: manu
category: process-method
tags: [kubelab, process-method, postgres, adr, planning]
---

# A closed epic is not a built substrate, and an ADR's "next" list is not a ticket

**Context**: Planning slice 1 of the forge task view (CONSOLE-004), whose read model, event table and usage counter all live in the `infra.postgres` tenant. CONSOLE-002 (#711, #714, #724) is closed and ADR-051 reads as settled, so the plan assumed a database layer to build on.

**Problem**: Reading the repository showed otherwise. ADR-051 lists the atlas schema, the DSN composition in `pkg/config` and the real `pg_isready` check as "Next (PR-1b)", and the migration Job as "Later (PR-3)". None of it exists: no atlas schema or `atlas.sum` is tracked, `apps/api/src/go.mod` has no Postgres driver, and nothing runs migrations. The epic closed with the Deployment and the secrets in place, and the ADR's backlog section was never turned into tickets, so no open item remembered it.

**Solution**: Check the substrate itself before sizing the slice that sits on it: `git ls-files | grep -i atlas`, the driver in `go.mod`, the step that applies migrations. Then park the question with two options on the epic (#2570) instead of building persistence on an assumption.

**Rule**: A closed ticket says its own acceptance criteria were met, not that what a later feature needs exists. When an ADR carries an "Implementation / backlog" list, each line either becomes a ticket in the same change or is struck from the ADR, since a list that looks planned and is not is read as work in hand. Before a spec depends on a layer, look for the layer.

**Tags**: `#planning` `#adr` `#postgres` `#console-004`
