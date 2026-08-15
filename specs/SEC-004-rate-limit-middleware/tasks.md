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

- [ ] Branch: fresh `feat/SEC-004-rate-limit-middleware` off `origin/master` (this spec's own docs work landed via a separate `docs/*` PR; implementation starts clean).
- [x] `proposal.md` is complete and acceptance criteria are testable — the one `[AGENT-DRAFT]` tag (blanket vs. selective scope) is resolved. ✓ 2026-08-14
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-14 — values measured against real staging traffic, the AC1 key-naming conflict with the VPS's own keys resolved by the user, `sourceCriterion` and shared-vs-per-router bucket semantics pinned as explicit implementation tasks below rather than left implicit.

## Implementation

### Part 1 — the Middleware object and its SSOT keys, proven to exist and match

- [ ] [P] [AC1] Add `edge.traefik.rate_limit_k3s_{average,burst,period}` to `common.yaml` (siblings of the existing VPS-only `edge.traefik.rate_limit_*` keys — see `proposal.md` Risks for why they can't be shared). Starting values from the 2026-08-14 measurement: `average: 30`, `burst: 150`, `period: 1s` — subject to revision if Part 4's burst drill says otherwise.
- [ ] [AC1] Add `infra/k8s/base/edge/rate-limit.yaml` — a `Middleware` object named `rate-limit`, mirroring `secure-headers.yaml`'s static-manifest pattern (values hand-set to match the new common.yaml keys, not templated — there is no generator precedent for Middleware *values* in this codebase, only for the per-route *list* via `_build_middlewares()`). Explicit `sourceCriterion: { requestHost: {} }` — do not rely on Traefik's default client-IP keying, which would happen to look "global" only because of klipper-lb's masquerade (#1067); see Risks. Register in `base/kustomization.yaml`'s `resources:`.
- [ ] [P] [AC1] Add a static test (e.g. `tests/infra/test_rate_limit_middleware.py`) asserting `rate-limit.yaml`'s `average`/`burst`/`period` match `common.yaml`'s `edge.traefik.rate_limit_k3s_*` — the "no hardcoded duplicate" guarantee for a manifest that (like `secure-headers.yaml`) isn't generator-templated. **Fails now** (file doesn't exist).
- [ ] [AC1] Deploy to staging (`make deploy-k8s ENV=staging`), confirm the Middleware object exists (`kubectl get middleware rate-limit -n kubelab`) and the new test passes.

### Part 2 — generator change, paired with the regenerated file (CI-GATE-002)

- [ ] [P] [AC2] Add a test asserting `_build_middlewares()` includes `"rate-limit"` in every returned list (extend whatever existing test already covers that function, e.g. alongside its `secure-headers`/`error-pages` assertions). **Fails now.**
- [ ] [AC2] [AC4] Add `"rate-limit"` to the `middlewares` list in `_build_middlewares()` (`toolkit/features/generator_k8s.py:399`). Same commit: regenerate `infra/k8s/overlays/{staging,prod}/generated/ingress.yaml` (`make deploy-k8s` or whatever target triggers generation — confirm via `make config-check-drift`, which must stay green in the same commit per CI-GATE-002/SEC-K8S-001).

### Part 3 — hand-written IngressRoutes, blanket

- [ ] [AC2] Add `rate-limit` to the `middlewares:` list of every hand-written `IngressRoute` not covered by Part 2's generator (17 files as of 2026-08-14 — re-grep `kind: IngressRoute` across `infra/k8s/base/` and `infra/k8s/overlays/` before starting, this list rots): `base/edge/errors.yaml`, `base/external/uptime-kuma.yaml`, `base/services/{homepage,minio,loki,grafana,authelia,n8n}.yaml`, `overlays/prod/{patches,gitea,traefik-dashboard,headscale,redirect-kubelab,argocd}.yaml`, `overlays/staging/{traefik-dashboard,pihole,redirect-kubelab}.yaml`. Position consistently with each route's existing `secure-headers`/`error-pages`/optional-auth chain per the ordering note in `proposal.md` Risks — do not use this task to reorder anything else.
- [ ] [P] [AC2] Add or extend a static test asserting every `IngressRoute` across base + both overlays' rendered output includes `rate-limit` in its middlewares (a `kubectl kustomize`-based coverage test, same spirit as `tests/test_spoke_rbac_covers_manifests.py`'s static-coverage pattern — catches the next new route that forgets it, not just today's 17). **Fails now.**

### Part 4 — the burst drill, exercised rather than assumed

- [ ] [AC3] In staging, exhaust the Homepage route's bucket with a burst above the configured threshold and confirm HTTP 429 (`curl`-loop or equivalent — bounded, staging-only). Then, **without waiting for refill**, immediately probe a *different* route (e.g. `grafana.staging.kubelab.live`) — a 429 there proves the bucket is shared across routers, a clean 200 proves per-router. Record which in `verification.md`; this determines what "blanket application" actually guarantees and may need a `proposal.md` correction if it contradicts the assumed design.
- [ ] [AC3] Wait for the bucket to refill per the configured `average`/`period` (or restart the drill against a route not yet exhausted), then confirm a clean request passes under threshold — per the CodeRabbit-flagged isolation requirement in `proposal.md`'s AC3, this must not inherit token state from the first half of the drill.
- [ ] [AC3] If Part 4's results contradict the draft `average: 30 / burst: 150` values from Part 1 (e.g., real concurrent-session traffic proves them too tight or needlessly loose), revise the common.yaml keys and redeploy before closing — the values are a draft until this drill confirms them, not before.

### Part 5 — prod (post-merge)

- [ ] [AC1] [AC2] After merge: `make deploy-k8s ENV=prod`, confirm `rate-limit` Middleware exists and every prod IngressRoute references it (same coverage test from Part 3, run against the prod overlay).

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
