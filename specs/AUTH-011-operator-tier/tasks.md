---
tags: [spec, tasks, templates]
created: "2026-09-26"
---

# Tasks - AUTH-011

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/operator-tier` ✓ 2026-09-26
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-09-26
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-09-26

## Implementation

- [x] [P] [AC1] Declare `argocd.app_version` next to `chart_version`; regenerate `platform.json` ✓ 2026-09-26
- [x] [AC1] Failing test: run `argocd admin settings rbac can` from the pinned image over the shipped `policy.csv` for every allow/deny pair ✓ 2026-09-26
- [x] [AC1] `role:operator` and `g, users, role:operator` in `infra/helm/argocd/values.yaml` ✓ 2026-09-26
- [x] [P] [AC2] Failing test: the role path maps users → Editor, e2e → Viewer, admins+users → Admin; the empty-groups guard still holds ✓ 2026-09-26
- [x] [AC2] Grafana `GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH` ✓ 2026-09-26
- [x] [P] [AC3] Failing test: `declared_tiers` is three-valued and each app maps it ✓ 2026-09-26
- [x] [AC3] `access_review.py`: `declared_tiers`, per-app tier maps, docstring ✓ 2026-09-26
- [x] [AC4] Amend ADR-062 D2 ✓ 2026-09-26
- [ ] `make test`, then PR
- [ ] [AC2] [AC3] Staging: Grafana Editor for `operator` after `make auth-review ENV=staging APPLY=1`
- [ ] [AC5] Prod after merge: `make deploy-argocd` (operator go-ahead: restarts Authelia), `make auth-review ENV=prod APPLY=1`, browser check of both halves

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Lint passes
- [ ] No unrelated changes in the diff
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/AUTH-011-operator-tier/features.json`):

```json
[
  {
    "id": "AUTH-011-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
