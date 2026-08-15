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
## Setup

- [x] Branch: fresh `feat/SEC-004-rate-limit-middleware` off `origin/master` (this spec's own docs work landed via a separate `docs/*` PR; implementation starts clean). ✓ 2026-08-15
- [x] `proposal.md` is complete and acceptance criteria are testable — the one `[AGENT-DRAFT]` tag (blanket vs. selective scope) is resolved. ✓ 2026-08-14
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-14 — values measured against real staging traffic, the AC1 key-naming conflict with the VPS's own keys resolved by the user, `sourceCriterion` and shared-vs-per-router bucket semantics pinned as explicit implementation tasks below rather than left implicit.

## Implementation

### Part 1 — the Middleware object and its SSOT keys, proven to exist and match

- [x] [P] [AC1] Add `edge.traefik.rate_limit_k3s_{average,burst,period}` to `common.yaml` (siblings of the existing VPS-only `edge.traefik.rate_limit_*` keys — see `proposal.md` Risks for why they can't be shared). Starting values from the 2026-08-14 measurement: `average: 30`, `burst: 150`, `period: 1s`. ✓ 2026-08-15 — confirmed by Part 4's burst drill, no revision needed.
- [x] [AC1] Add `infra/k8s/base/edge/rate-limit.yaml` — a `Middleware` object named `rate-limit`, mirroring `secure-headers.yaml`'s static-manifest pattern. Register in `base/kustomization.yaml`'s `resources:`. ✓ 2026-08-15 — **`sourceCriterion.requestHost: {}` from the proposal was wrong**: a dry-run apply rejected it (`expected boolean, got &{map[]}`); Traefik's CRD wants `requestHost: true`. Caught before any real cluster mutation, not after. `tests/test_rate_limit_middleware.py` (not `tests/infra/`, following this repo's actual `tests/test_k8s_generator_*.py` naming convention rather than the draft path above).
- [x] [P] [AC1] Static test asserting `rate-limit.yaml`'s values match `common.yaml`'s `edge.traefik.rate_limit_k3s_*` (mirrors `tests/test_spoke_rbac_covers_manifests.py`'s no-kubectl pattern). ✓ 2026-08-15
- [x] [AC1] Deploy to staging, confirm the Middleware object exists and values are live. ✓ 2026-08-15

### Part 2 — generator change, paired with the regenerated file (CI-GATE-002)

- [x] [P] [AC2] Add a test asserting `_build_middlewares()` includes `"rate-limit"` in every returned list. ✓ 2026-08-15 — `tests/test_k8s_generator_middlewares.py` (no prior test existed for this function at all).
- [x] [AC2] [AC4] Add `"rate-limit"` to the `middlewares` list in `_build_middlewares()` (`toolkit/features/generator_k8s.py:399`, positioned between `secure-headers` and `error-pages`, matching the VPS's own ordering). Same commit: regenerated `infra/k8s/overlays/{staging,prod}/generated/ingress.yaml` via `make config-generate ENV=<env>`. ✓ 2026-08-15 — `make config-check-drift ENV=staging` and `ENV=prod` both green after commit.

### Part 3 — hand-written IngressRoutes, blanket

- [x] [AC2] Add `rate-limit` to the `middlewares:` list of every hand-written `IngressRoute` (re-grepped fresh 2026-08-15, list matched the 2026-08-14 draft exactly — 17 files, 18 route entries). ✓ 2026-08-15 — `overlays/prod/patches.yaml` alone carried 9 of the 18 (its strategic-merge routes fully replace the base's middlewares list). Two routes (base + prod `catch-all`) had no middlewares list at all before this.
- [x] [P] [AC2] Static coverage test, `tests/test_rate_limit_coverage.py` — reads manifest files directly (no `kubectl kustomize`, mirroring `tests/test_spoke_rbac_covers_manifests.py`'s CI-runner-friendly pattern rather than the kustomize-based approach originally drafted here). ✓ 2026-08-15 — cross-checked against the actual `kubectl kustomize` output for both envs too (14 staging + 16 prod rendered routes, zero missing), not just the source files.

### Part 4 — the burst drill, exercised rather than assumed

- [x] [AC3] In staging, exhausted the Homepage route's bucket (`ab -n 300 -c 100` against `home.staging.kubelab.live`) — 88/300 got HTTP 429, 212/300 got 200 (expected ≈223 admits at burst=150 + ~2.45s refill at average=30/s; 212 observed, consistent). Immediately probed `grafana.staging.kubelab.live` (different route): 5/5 clean 302 (its normal unauthenticated redirect, not 429). Then burst-tested grafana directly to rule out "exempt route" as the explanation: 104/300 got 429 under its own load. **Confirmed: per-router, independent buckets, not shared.** ✓ 2026-08-15 — full numbers and the rationale for why per-router is the better outcome in `proposal.md` Risks.
- [x] [AC3] Confirmed a clean request passes below threshold, **discriminated against a genuinely-attached limiter** (not just "some time passed") — chained deploy → read live middlewares list → single probe in one command, avoiding the race in the note below. 200 OK. ✓ 2026-08-15
- [x] [AC3] Draft values confirmed by the drill, no revision needed: `average: 30`, `burst: 150`, `period: 1s`. ✓ 2026-08-15

> **Unplanned finding, filed as #1083**: the first two drill attempts silently lost their applied Middleware mid-test — staging's Argo CD Application (`selfHeal: false` per ADR-037) still auto-syncs on *any new git revision*, and master moved (merges from parallel worktree lanes) during this session. `kubectl get application kubelab-staging -o json --show-managed-fields` on the affected `IngressRoute` showed `argocd-controller Update` ~25-30s after the manual apply, reverting it to master's state. This is not `selfHeal: false` malfunctioning — the flag only suppresses *drift* reconciliation, not *new-revision* sync — but it is an unstated gap in ADR-037's "staging deploys persist" premise on multi-lane days. Root-caused with a read-only `kubectl get application ... status.history` check (not fixed here — separate ticket, separate scope). Also retroactively explains two earlier zero-429 `ab` runs during this same session: the middleware had already been reverted minutes before those requests were sent, so they are not evidence against the limiter.

### Part 5 — prod (post-merge)

- [ ] [AC1] [AC2] After merge: `make deploy-k8s ENV=prod`, confirm `rate-limit` Middleware exists and every prod IngressRoute references it (same coverage test from Part 3, run against the prod overlay).

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-08-15
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command ✓ 2026-08-15 — all 4 commands run and pass
- [x] Type checks pass ✓ 2026-08-15 (no new typed code — YAML + generator list literal only)
- [x] Lint passes ✓ 2026-08-15 — yamllint, markdownlint, pre-commit all clean
- [x] No unrelated changes in the diff (no scope creep) ✓ 2026-08-15
- [x] `verification.md` filled in ✓ 2026-08-15
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
