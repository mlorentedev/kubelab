---
tags: [spec, tasks, templates]
created: "2026-11-04"
id: "OPS-065-edge-backend-timeouts"
type: spec-tasks
status: active
owner: manu
---

# Tasks - OPS-065-edge-backend-timeouts

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch per PR from `master`; this spec lands first, on its own
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions" (the values close only when the data is in)

## Implementation

> Draft order. The values, and so every task after "Measure", wait for the data.

- [x] Collect: #3106 merged and applied in prod (`make provision NODE=vps ENV=prod TAGS=k3s`, dry run first)
- [x] ~~[AC4] Read Headscale's access-log lines in prod~~ superseded 2026-11-12: the log records upgraded connections with status `0` and their whole life, not the `101`. Headscale ships as an exception instead (ADR-076 D2) and AC4 is amended
- [x] Measure: after seven or more days, the slow-request distribution per router from Loki, through a toolkit command, not by hand. It reports each router's request count beside the distribution, so a router with no slow requests reads as "no sample", not as "needs no exception" ✓ 2026-11-12 (`make edge-slow-routes`; figures in verification.md)
- [x] For each route with requests longer than the candidate bound: measure its time to first header directly, and list it only if its headers are late. The default is sized from these time-to-first-header figures, never from the access-log durations, which include the body ✓ 2026-11-12 (none listed; ADR-076 Context 1)
- [x] [AC5] ADR: default, exceptions with their measurements, `dialTimeout`, `idleConnTimeout`, duration versus count ✓ 2026-11-12 (ADR-076, #3366)
- [x] [AC3] Write the failing coverage test: every route has the default or a declared exception, and every exception matches a route ✓ 2026-11-12 (`tests/test_edge_backend_timeouts.py`)
- [x] [AC2] [AC3] Declare the exceptions in `common.yaml` (`edge.backend_timeouts.exceptions`) ✓ 2026-11-12. Both routes that use one are hand-written overlay manifests, not generated, so the test holds each `ServersTransport` and its reference to the declaration instead of a generator emitting them
- [x] [AC1] Write the stuck-backend fixture for staging ✓ 2026-11-12 (#3415)
- [x] [AC1] [AC2] e2e expectations: the default route answers the edge's 504 near the bound, `/exception` is still open past it ✓ 2026-11-14 (`tests/e2e/test_backend_timeouts.py`)
- [x] Spoke RBAC writes `serverstransports` (#3422), then `make register-spoke ENV=staging` and `ENV=prod`; `can-i create serverstransports.traefik.io` answers `yes` in both ✓ 2026-11-12 (lesson-743)
- [x] [AC1] Set the default in the `k3s_server` HelmChartConfig ✓ 2026-11-12
- [x] [AC1] [AC2] Staging: provision, the fixture is cut, an exception holds, `make test-e2e ENV=staging` ✓ 2026-11-13 (verification.md)
- [x] [AC4] Prod (owner): dry run, apply, VPN check (re-register a node, MagicDNS), `make test-e2e ENV=prod` ✓ 2026-11-14 (verification.md)
- [ ] [AC4] Lift the Headscale exception, deploy, and re-register a node under the default

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

Minimal `features.json` skeleton (drop into `<repo>/specs/OPS-065-edge-backend-timeouts/features.json`):

```json
[
  {
    "id": "OPS-065-edge-backend-timeouts-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
