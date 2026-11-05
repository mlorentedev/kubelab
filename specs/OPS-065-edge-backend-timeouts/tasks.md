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

- [ ] Collect: #3106 merged and applied in prod (`make provision NODE=vps ENV=prod TAGS=k3s`, dry run first)
- [ ] [AC4] Read Headscale's access-log lines in prod: the `101` and the long upgraded connection
- [ ] Measure: after seven or more days, the slow-request distribution per router from Loki, through a toolkit command, not by hand
- [ ] For each route with requests longer than the candidate bound: measure its time to first header directly, and list it only if its headers are late
- [ ] [AC5] ADR: default, exceptions with their measurements, `dialTimeout`, `idleConnTimeout`, duration versus count
- [ ] [AC3] Write the failing coverage test: every route has the default or a declared exception, and every exception matches a route
- [ ] [AC2] [AC3] Declare the exceptions in `common.yaml`; the generator emits the `ServersTransport` and the reference
- [ ] [AC1] Write the stuck-backend fixture for staging and the test that it is cut at the bound
- [ ] [AC1] Set the default in the `k3s_server` HelmChartConfig
- [ ] [AC1] [AC2] Staging: provision, the fixture is cut, an exception holds, `make test-e2e ENV=staging`
- [ ] [AC4] Prod: dry run, apply, VPN check (re-register a node, MagicDNS), `make test-e2e ENV=prod`

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
