---
tags: [spec, verification]
created: "2026-09-23"
---

# Verification - TOOL-080-forge-pr-reviewer

## Evidence

- [ ] AC1: comment id, author and timestamp on a real `personal/resume` PR
- [ ] AC2: the same comment id after a push, with `updated_at` later than the push
- [ ] AC3: HTTP status for an unsigned and a wrongly signed POST; test `<name>`
- [ ] AC4: title and body byte-identical before and after; test `<name>`
- [ ] AC5: measured scope requirement (below); test `<name>`; `GET /users/<reviewer>/repos` returns `[]`
- [ ] AC6: tests `<names>`; orphan audit output
- [ ] AC7: reconcile apply output, then a second run with no changes
- [ ] AC8: alert fired, and its timestamp

## Pre-spec measurement (2026-09-24, read-only)

The probe from #1823:

- `pragent/pr-agent:0.45.0` in CLI mode, `CONFIG__GIT_PROVIDER=gitea`, NaN backend, `CONFIG__PUBLISH_OUTPUT=false`, run against resume PR 270 with the `hefesto` token (`read` on the repo).
- It fetched a full diff of 8,903 tokens, the model answered in about 2.5 s, and it produced a `PR Reviewer Guide`. Nothing was posted.
- The server image `pragent/pr-agent:0.45.0-gitea_app` is digest `sha256:750c6cf8532b7aa81ef55a71cce0d8c24485cd18cbdcca21d3885788ce2b69f4`. Its default command is gunicorn with UvicornWorker on `:3000` (2 to 4 workers from the cgroup CPU limit), and it declares no user.

## Test status

- Test suite: `<command> -> <output>`
- No regressions in the existing suite: yes / no

## Decisions made during implementation

- 2026-09-24, Manu: run it in the cluster, copy `NAN_API_KEY` into SOPS, and write the spec before any code.
- Hook events are `pull_request` only. Slash commands stay out until an author filter exists (proposal, Out of scope).

## Promotion candidates

- [ ] Lesson: <yes / no>
- [ ] ADR: the ADR-062 D1 amendment for a reviewer identity, shared with AUTH-007
- [ ] Pattern: <yes / no>

## Archive checklist

- [ ] `status: archived`, folder moved to `specs/archive/`
- [ ] #1823 closed by the PR that archives this spec
