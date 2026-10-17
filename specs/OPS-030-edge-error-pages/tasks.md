---
tags: [spec, tasks, templates]
created: "2026-10-16"
---

# Tasks - OPS-030-edge-error-pages

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from main: `feat/OPS-030-edge-error-pages`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

> Three PRs, in this order. PR 1 is tests and deletions, PR 2 the nginx/image change (`fix:` so release-please builds it), PR 3 the owner-decided prod coverage.

- [ ] [AC6] Owner decides, per prod route without `error-pages` (`argocd`, `authelia`, `loki`, `vikunja`, `n8n`): add the middleware or declare the exception. Record it on #1753
- [x] [P] [AC1] Failing test `tests/test_error_pages_reachable.py`: every `errors/*.html` is targeted by a Middleware status range, an nginx `error_page` or the catch-all. Expected: FAIL on 401, 408, 429, 500, maintenance
- [x] [AC3] Delete `401.html`, `408.html`, `429.html`, `500.html`, `maintenance.html` and their `error_page` lines; update `tests/test_error_pages_markup.py` (page count, orphan scan)
- [ ] [P] [AC2] Failing test `tests/test_ingressroute_error_page_coverage.py`: render both overlays, every IngressRoute carries `error-pages` or is in `edge.errors.coverage.exceptions`. Expected: FAIL on the prod gaps
- [ ] [AC2] Declare `edge.errors.coverage.exceptions` in `common.yaml` (`headscale`, `catch-all`, `kubelab-redirect`, `brand-assets`, webhook routes, each with a reason); the test reads it with `yaml.safe_load`
- [x] [AC5] Failing test: built image answers JSON for `Accept: application/json` on `/errors/502.html`, `/errors/503.html`, `/errors/504.html` and on an unknown path (status unchanged), HTML otherwise
- [x] [AC4][AC5] `edge/errors/nginx.conf`: `map $http_accept` negotiation, `no-store`, `X-Robots-Tag`, `Retry-After` on 503/504, `access_log` on `/errors/`; JSON bodies next to the HTML pages
- [ ] [AC6] Apply the owner's decision: add the middleware or the exception; the coverage test goes green
- [ ] Update `CLAUDE.md` / ADR-072 status to `accepted` when PR 1 merges

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/OPS-030-edge-error-pages/features.json`):

```json
[
  {
    "id": "OPS-030-edge-error-pages-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
