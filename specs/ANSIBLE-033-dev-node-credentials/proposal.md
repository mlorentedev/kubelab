---
id: "ANSIBLE-033-dev-node-credentials"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-07"
issue: "kubelab#888"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-033: Dev node credentials — interim staging-scoped identity

> **Naming**: file lives at `<repo>/specs/ANSIBLE-033-dev-node-credentials/proposal.md`. `ANSIBLE-033-dev-node-credentials` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #888: ANSIBLE-033: dev node credentials — interim staging-scoped identity (PR-1c of ADR-058) -->

The dev node ships with a working toolchain and no identity. Verified on ace2 2026-08-07: node/go/python pinned and resolving, `nvim`/`gh`/`git`/`docker`/`tmux` present, agent workspaces created — but `gh auth status` reports not logged in and `~/.ssh` holds only a public key. You can edit, build and run; you cannot clone a private repo, push, or use `gh`. That gap is the whole distance between "there is a dev node" and "I work there", and it blocks the agent workflow D1 exists to enable.

## What

Concrete behavior change. What does the system do after this PR that it did not do before? Observable, not implementation-focused.

## Out of scope

Things this PR explicitly does NOT include. Forces a sharp boundary and prevents scope creep.

-
-

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. If any item here is unresolved, do not move to `tasks.md` yet.

-
-

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] Outcome 1
- [ ] Outcome 2
- [ ] Outcome 3

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
