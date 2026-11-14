---
spec: "OPS-065-edge-backend-timeouts"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "3fa4a408f188e834d0e3fe72b3f61454cc932854"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-14"
---

## Adversarial review

**Scope**: OPS-065-edge-backend-timeouts
**Sources**: `specs/OPS-065-edge-backend-timeouts/{proposal,tasks,verification}.md`, `git diff 3a24fdd3bb9b4268682b7770c5f6e368e5f80320...HEAD`

### Spec and task alignment

The change bounds how long Traefik waits for upstream backends across KubeLab's edge (`k3s_server` HelmChartConfig `serversTransport.forwardingTimeouts.responseHeaderTimeout=60s` and `dialTimeout=5s`), adds static route-coverage assertions, provides an in-cluster stuck-backend fixture in staging, records ADR-076, and documents operational delivery via lesson-743.

Alignment per acceptance criterion:
- **AC1 (Default timeout cuts stuck backend & returns edge error page)**: Implemented via Traefik `--serversTransport.forwardingTimeouts` CLI args and verified with the staging fixture `stuck-backend.staging.kubelab.live`. Freshly re-verified live in this review session (`tests/e2e/test_backend_timeouts.py::TestBackendTimeouts::test_default_route_answers_the_edges_504_at_the_bound` PASSED in 60.56 s, receiving 504 and matching the edge's branded 504 error page).
- **AC2 (Declared exception route keeps longer bound)**: Implemented via `ServersTransport` CRD (`stuck-backend-exception`) referenced from the `/exception` route of `stuck-backend.staging.kubelab.live` and declared in `common.yaml` (`edge.backend_timeouts.exceptions`). Freshly re-verified live in this review session (`tests/e2e/test_backend_timeouts.py::TestBackendTimeouts::test_exception_route_stays_open_past_the_bound` PASSED in 75.28 s, holding connection open past the 60 s default).
- **AC3 (Route coverage tests and static failure gates)**: Covered by `tests/test_edge_backend_timeouts.py` (7 passed in 1.25 s). The test renders staging and prod overlays, asserting that every route referencing a `ServersTransport` is declared in `common.yaml`, that the transport exists in the overlay, that `responseHeaderTimeout` matches the declaration, that `dialTimeout` restates the default 5 s bound, and that no unreferenced exceptions exist. Mutation probes confirmed tests fail if arguments or declarations are altered.
- **AC4 (Headscale lifecycle: exception -> deploy -> lift -> verify)**: Shipped initially with an exception in #3446; node re-registered under #3493; lifted in #3503; ace2 re-registered under default with peers online (verified 2026-11-14T07:26:44Z); unit test `test_headscale_runs_under_the_default_since_a_node_re_registered_through_it` permanently enforces that Headscale has no exception.
- **AC5 (ADR-076 recorded and accepted)**: Recorded in `docs/adr/adr-076-edge-backend-timeouts.md` with status `accepted` in #3366, detailing measurements, default 60 s header timeout, 5 s dial timeout, 90 s idleConnTimeout, and rejection of `inFlightReq`.

All implementation tasks in `tasks.md` are completed and checked. The contract set (`proposal.md`, `tasks.md`, `features.json`) matches the launcher's digests recorded in `review-request.json`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | measurement | Header latency for non-Headscale routes (Gitea, Uptime Kuma, Console) was inferred from access log `OriginDuration` and HTTP status codes rather than direct TTFB probes, and the 5 s dial timeout was not directly measured before deployment. | `verification.md` ("Decisions made during implementation"); prod access log showed zero 504s in initial 3h window; tracked in follow-up issue #3520. | `tests/test_edge_slow_routes.py` (log parser); UNTESTED for direct TTFB probes. | outside-contract (verification.md / ticket #3520) |
| Minor | REAL | code-quality | Missing generic type parameters on `dict` in `tests/test_edge_slow_routes.py` (lines 22 and 64) trigger mypy `[type-arg]` errors when mypy is run directly against tests. | `.venv/bin/mypy tests/test_edge_slow_routes.py` fails with 2 `[type-arg]` errors; `make type` checks only `toolkit/`. | `tests/test_edge_slow_routes.py` | tests |
| Minor | THEORETICAL | spec-hygiene | Acceptance criteria checkboxes AC1–AC4 in `proposal.md` and closing items in `tasks.md` remain unchecked (`- [ ]`) in git despite all criteria being verified and closed in `verification.md` and `features.json`. | `proposal.md` lines 49-52; `tasks.md` lines 45-51. | UNTESTED | spec (contract set closed; do NOT edit post-review) |
| Minor | THEORETICAL | resilience | `tests/test_edge_backend_timeouts.py` silently skips when `kubectl` is missing from PATH (`shutil.which("kubectl") is None`), which could mask failures in an environment lacking `kubectl`. | `tests/test_edge_backend_timeouts.py` line 48. | `tests/test_edge_backend_timeouts.py` | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All criteria verified live in staging and prod; negative paths tested; TTFB for minor routes inferred from duration. |
| Verification       | A | All 5 ACs proven with reproducible commands, fresh live e2e execution (60.56s & 75.28s), and detailed logs. |
| Scope              | A | Perfectly contained to edge timeouts, ADR-076, stuck-backend fixture, spoke RBAC, and access log telemetry. |
| Reliability        | A | Changes are idempotent (`changed=0` on re-run), spoke RBAC applied before manifests, stuck-backend pod sandboxed. |
| Maintainability    | A | All functions under 40 lines and CC <= 10; unit, e2e, and schema coverage cleanly decoupled; ruff clean. |
| Handoff-readiness  | A | Lesson-743 and ADR-076 persisted in repo docs; decisions, caveats, and follow-up ticket #3520 recorded. |

### Verdict
PASS WITH GAPS

### Recommended next steps

The contract set (`proposal.md`, `tasks.md`, `features.json`) is closed and its digests are locked; editing contract files now would invalidate this review. Recommendations are routed by set:

1. **Outside-contract / follow-up ticket (Major finding)**: Maintain tracking on issue #3520 to inspect prod Loki access logs after seven full days of production traffic to confirm no legitimate long queries (Gitea git clone/stream, Uptime Kuma socket.io, Console) trigger spurious 504 errors.
2. **Tests (Minor finding)**: In a subsequent PR, annotate `dict` return types in `tests/test_edge_slow_routes.py` as `dict[str, Any]` to keep direct mypy runs clean.
3. **Tests (Minor finding)**: Replace `pytest.skip` with an explicit assertion or ensure CI runner matrices mandate `kubectl` availability.
4. **Spec archive gate**: Proceed with `dotf spec archive OPS-065-edge-backend-timeouts`. Archiving is **ADVISABLE** in the current state.
