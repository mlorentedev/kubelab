---
tags: [spec, tasks]
created: "2026-11-14"
id: "AI-013-hermes-liveness"
type: spec-tasks
status: active
owner: manu
---

# Tasks - AI-013-hermes-liveness

> TDD order. The design is frozen at `implementing`; each behavior is tested before its implementation.

## Setup

- [x] Persistent lane `feat-lane-primary` claimed as `feat/hermes-liveness` from `origin/master`; issue #2175 self-assigned.
- [x] Proposal complete; candidates evaluated and no unresolved question remains.
- [x] Work-gate and WIP override recorded in the proposal.

## Implementation

- [x] [AC1] Add failing Compose/systemd wiring tests for the healthcheck, notification hooks and two-minute timer.
- [x] [AC1] Implement the bounded Compose healthcheck and systemd watcher/timer templates.
- [x] [AC2] Add failing executable probe tests for healthy, starting, unhealthy, missing and Docker-error results, plus recovery semantics.
- [x] [AC2] Implement the root-owned probe script with strict container-name validation and no credential handling.
- [x] [AC3] Add failing on-demand lifecycle tests: no persistent/catch-up or external monitor and a declared boot grace period.
- [x] [AC3] Implement any minimal timer/runbook changes required by those tests.
- [x] [AC4] Add failing configured/unconfigured role-ordering tests.
- [x] [AC4] Install/start the watcher only after gateway health succeeds; disable/remove it when Hermes is absent.
- [x] [AC5] Run focused suites, Ansible parsing, lint/type checks and provisioning through a final `changed=0` on coordinated ace2 access.
- [x] [AC5] Operator-approved clean stop/start produced one `ops-log` incident and `recovered … after 1 failed runs`; ace2 was not powered off.
- [x] Record local evidence and explicit pending live gates in `verification.md`, `features.json` and the Hermes runbook; final live evidence remains to be appended.

## Closing

- [x] Every acceptance criterion has a non-vacuous `features.json` verification and observed evidence or an explicitly named pending live gate.
- [x] Lint, type and relevant test suites pass; diff stays within AI-013.
- [x] Knowledge hygiene and newly discovered test-contract defects are recorded in-session.
- [x] Draft PR #3558 opened with `Closes #2175` after live acceptance; independent review findings then applied and live-verified.
- [x] Owner chose direct fixes for the two remaining gaps instead of AI-034/AI-035 tickets: bounded startup grace and failure-path timer restoration are implemented with tests.
- [ ] Live-verify the direct `starting` grace and provisioning; keep failure restoration covered by structure/parse tests (no deliberately broken provision), then obtain a fresh independent verdict.
- [ ] CI and every reviewer output dispositioned; no merge from the implementing session.
- [ ] Independent adversarial review before a separate curator archives the spec.
- [ ] `/handoff` completed.
