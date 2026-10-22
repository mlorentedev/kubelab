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

- [x] Branch created from main: the work landed on per-PR branches (`fix/edge-error-pages-reachability`, `fix/edge-error-pages-coverage`, `fix/edge-error-pages-negotiation`) instead of one `feat/OPS-030-edge-error-pages` ✓ 2026-10-17
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-10-16
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-10-17 (the prod gaps were decided per route in #2361)

## Implementation

> Three PRs, in this order. PR 1 is tests and deletions, PR 2 the nginx/image change (`fix:` so release-please builds it), PR 3 the owner-decided prod coverage.

- [x] [AC6] Owner decides, per prod route without `error-pages` (`argocd`, `authelia`, `loki`, `vikunja`, `n8n`): add the middleware or declare the exception. Record it on #1753 ✓ 2026-10-17: decided in #2361 (merge `ae331d1c`), recorded in its body and in ADR-072 decision 6, not as a comment on #1753
- [x] [P] [AC1] Failing test `tests/test_error_pages_reachable.py`: every `errors/*.html` is targeted by a Middleware status range, an nginx `error_page` or the catch-all. Expected: FAIL on 401, 408, 429, 500, maintenance ✓ 2026-10-17 (#2360)
- [x] [AC3] Delete `401.html`, `408.html`, `429.html`, `500.html`, `maintenance.html` and their `error_page` lines; update `tests/test_error_pages_markup.py` (page count, orphan scan) ✓ 2026-10-17 (#2360)
- [x] [P] [AC2] Failing test `tests/test_error_pages_coverage.py`: render both overlays, every IngressRoute carries `error-pages` or is in `edge.errors.coverage.exceptions`. Expected: FAIL on the prod gaps ✓ 2026-10-17 (#2361)
- [x] [AC2] Declare `edge.errors.coverage.exceptions` in `common.yaml` (`headscale`, `catch-all`, `kubelab-redirect`, `brand-assets`, webhook routes, each with a reason); the test reads it with `yaml.safe_load` ✓ 2026-10-17 (#2361)
- [x] [AC5] Failing test: built image answers JSON for `Accept: application/json` on `/errors/502.html`, `/errors/503.html`, `/errors/504.html` and on an unknown path (status unchanged), HTML otherwise ✓ 2026-10-17 (#2371)
- [x] [AC4][AC5] `edge/errors/nginx.conf`: `map $http_accept` negotiation, `no-store`, `X-Robots-Tag`, `Retry-After` on 503/504, `access_log` on `/errors/`; JSON bodies next to the HTML pages ✓ 2026-10-17 (#2371; `access_log` is the inherited http-level one, see Closing)
- [x] [AC6] Apply the owner's decision: add the middleware or the exception; the coverage test goes green ✓ 2026-10-17 (#2361)
- [x] Update `CLAUDE.md` / ADR-072 status to `accepted` when PR 1 merges ✓ 2026-10-17 (ADR-072 reads Accepted, #2360; the `CLAUDE.md` rule on the new-IngressRoute exception is in place)

## Closing

> Disposition 2026-10-22 (archive): all implementation PRs merged (#2336, #2346, #2360, #2361, #2371). The h1, robots and orphaned-asset items of #1753 landed in #2336 and #2346, ahead of this spec. Unticked boxes and where they are carried:
> - Every AC covered by a test: AC4's `access_log` clause is not asserted by any test. `access_log` is on for `/errors/` by inheritance (`edge/errors/nginx.conf:22`) and no `access_log off` sits in those locations, but removing that inheritance would leave the suite green. Carried by #2617 (OPS-044).
> - Type checks, lint and scope: not re-run, because the archive changes no code. The work PRs ran them in CI.
> - The CrowdSec ban page (ADR-072 phase 2, out of scope here) is carried by #2368.
> - #1753 stays open only because nothing closed it; every item in it has landed.

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [x] PR opened referencing this spec folder

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
