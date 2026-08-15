---
tags: [spec, tasks]
created: "2026-08-14"
---

# Tasks - SEC-004-rate-limit-middleware

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.
>
> **Not yet broken into concrete tasks.** The blanket-vs-selective route-scope question is resolved (blanket, confirmed by the user 2026-08-14 — see `proposal.md` "What"). One open item remains: measure real request rates for the noisiest staging route per the "Risks" note on reusing the VPS's `50/s`/`25` unmeasured, then write the task breakdown in the same style as OBS-010's `tasks.md` (this repo, same spec folder pattern) — Middleware manifest -> generator change + regenerated `ingress.yaml` for both envs (paired in one commit per the CI-GATE-002 constraint) -> per-route middleware list updates -> burst-drill test exercised in staging, not assumed.

## Setup

- [x] Branch: work done so far lives on `docs/IDP-031-coderabbit-evidence-fix` (investigation only, no code) — a fresh `feat/SEC-004-rate-limit-middleware` branch off `origin/master` is still needed once implementation starts. ✓ 2026-08-14
- [x] `proposal.md` is complete and acceptance criteria are testable — the one `[AGENT-DRAFT]` tag (blanket vs. selective scope) is resolved. ✓ 2026-08-14
- [ ] No open questions left in `proposal.md` "Risks / open questions" — one remains: the values re-measurement

## Implementation

(To be written once the open questions above are resolved.)

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/<feature-id>/features.json`):

```json
[
  {
    "id": "SEC-004-rate-limit-middleware-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
