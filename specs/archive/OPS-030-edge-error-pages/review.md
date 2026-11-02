---
spec: "OPS-030-edge-error-pages"
verdict: "PASS WITH GAPS"
reviewed_sha: "8063633df30811ebe261c8776e075b4ff420a21b"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-10-21"
---

## Adversarial review

**Scope**: OPS-030-edge-error-pages
**Sources**: `specs/OPS-030-edge-error-pages/{proposal,tasks,verification}.md` + git diff `088ae29ecb9f7d9801b7f4f1329e5427da3776cb...HEAD`

### Spec and task alignment
- **Acceptance criteria vs implementation**:
  - AC1 (reachability test for error pages): Met. `tests/test_error_pages_reachable.py` checks that every HTML page in `edge/errors/html/errors/` is targeted by a Middleware status range, an nginx `error_page` for a status nginx emits, or is a declared source page. Verified via mutation: introducing a dummy `418.html` reliably fails the test.
  - AC2 (route coverage test with reasoned exceptions): Met. `tests/test_error_pages_coverage.py` renders both staging and prod overlays (`kubectl kustomize`) and asserts every IngressRoute rule has `error-pages` middleware or matches an entry in `edge.errors.coverage.exceptions` in `infra/config/values/common.yaml`. Verified via mutation: removing an exception causes test failure.
  - AC3 (deletion of 5 unreachable pages, keeping 403 as ban-page source): Met. `401.html`, `408.html`, `429.html`, `500.html`, and `maintenance.html` are deleted. `403.html` is retained and tracked as `SOURCE_PAGES` in reachability tests.
  - AC4 (response headers: `no-store`, `noindex`, `Retry-After`, and `access_log`): Met in runtime behavior, partially tested. `tests/test_error_pages_nginx.py` asserts `no-store`, `noindex`, and `Retry-After` on 503/504. The `access_log` clause is not asserted by any test; logging is active via inheritance from the `http` block in `edge/errors/nginx.conf:22`, but breaking this inheritance would not fail CI. This is tracked in bitácora issue #2617.
  - AC5 (content negotiation via `Accept: application/json`): Met. The image negotiates JSON for gateway errors (502-504) and catch-all 404, returning `{"error": {"status", "title", "message"}}` with the original status code, and serving HTML otherwise.
  - AC6 (prod routes decided per owner): Met. `authelia` (prod), `vikunja`, and `n8n` UI carry `error-pages`; `argocd`, `loki`, `n8n` webhooks, and `pr-agent` are declared exceptions with explicit reasons in `common.yaml`.
- **Tasks alignment**: All implementation tasks are ticked. In the closing checklist, the unticked boxes for type checks, linting, and 100% test coverage accurately reflect the known gaps (untested access log, ruff/mypy warnings in test scripts).
- **Features verification**: All 5 items in `features.json` carry `"state": "passing"` and non-vacuous evidence corresponding to passing test commands (52 passed, 1 skipped).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | observability / testing | AC4 specifies `access_log` is on for `/errors/`, but no test asserts it. Adding `access_log off;` to `location /errors/` leaves the test suite 100% green. | Code inspection of `test_error_pages_nginx.py`; mutation test confirms suite passes with logging disabled. Implementer acknowledged in tasks.md/verification.md; tracked by #2617 (OPS-044). | UNTESTED | tests (`tests/test_error_pages_nginx.py` via follow-up #2617) |
| Minor | REAL | code quality / lint & types | `tests/test_error_pages_nginx.py` has two static analysis failures: line 43 exceeds line length limit (130 > 120, Ruff E501), and line 71 triggers Mypy `attr-defined` (`"HTTPResponse" has no attribute "code"`). | `poetry run ruff check tests/test_error_pages_nginx.py` returns exit 1; `poetry run mypy tests/test_error_pages_nginx.py` returns exit 1. | `ruff check` / `mypy` CLI runs | tests (`tests/test_error_pages_nginx.py`) |
| Minor | REAL | dead code / config hygiene | `edge/errors/nginx.conf` retains lines 58-60 (`error_page 502`, `503`, `504`), but nginx here serves only static files and never emits 5xx itself (`_nginx_emits()` is `{404}`). Traefik requests static files directly. | `tests/test_error_pages_reachable.py:88` explicitly asserts `assert _nginx_emits() == {404}`. Directives are inert leftover decoration. | `tests/test_error_pages_reachable.py::test_the_scan_sees_the_sources` | code (`edge/errors/nginx.conf`) |
| Minor | REAL | consistency / source page leak | Direct GET on `/errors/403.html` returns 200 OK with HTML, but requesting with `Accept: application/json` returns 404 (rewrites to non-existent `403.json`). 403.html is bundled in image as source for future ban plugin, not a served page. | Direct HTTP probe to built image: `GET /errors/403.html` gives 200 OK; `GET /errors/403.html` with `Accept: application/json` gives 404. | `tests/test_error_pages_reachable.py::test_every_served_page_has_a_json_twin_with_its_own_status[403.html]` (skipped by design) | code (Phase 2 #2368 when ban page is externalized to Helm mount) |
| Minor | THEORETICAL | test robustness | `_middleware_statuses()` scans `infra/k8s.rglob("*.yaml")` directly instead of rendering overlays with kustomize. An unreferenced dead YAML declaring a Middleware could theoretically make an orphaned page appear reachable. | `tests/test_error_pages_reachable.py:37` reads raw files on disk; currently all Middlewares are valid and active. | UNTESTED | tests (`tests/test_error_pages_reachable.py`) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All criteria met in running system; AC4 access_log unasserted in test suite but functionally working via inheritance. |
| Verification       | B | Reproducible test suite covers criteria (52 passed, 1 skipped for 403 source page); mutation proofs demonstrated. |
| Scope              | A | Perfectly adheres to proposal and ADR-072; out-of-scope ban page and rate-limit branding cleanly deferred to #2368. |
| Reliability        | B | Clean error handling, no-store caching safeguards, and security header preservation; access log lacks regression guard. |
| Maintainability    | B | Cyclomatic complexity <= 15 on all functions; clear structure; minor ruff E501 and mypy typing errors in test script. |
| Handoff-readiness  | A | ADR-072 accepted, Lesson 584 captured, PR links verified, and known gaps explicitly ticketed and dispositioned. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- **Archiving recommendation**: Archiving `specs/OPS-030-edge-error-pages` via `dotf spec archive` is **advisable** in the current state. The core contract is satisfied, all 5 features in `features.json` are verified green with captured evidence, and all open items are tracked with existing GitHub issues (#2617 and #2368).
- **Follow-up actions outside contract set**:
  - Implement automated verification of `access_log` output against the running container in `tests/test_error_pages_nginx.py` under issue #2617 (OPS-044).
  - Format line 43 in `tests/test_error_pages_nginx.py` (split across lines to satisfy line length <= 120) and adjust typing on line 71 (`getattr(resp, "code", getattr(resp, "status", 200))`) to satisfy Ruff and Mypy.
  - When Phase 2 (#2368) mounts `403.html` into Traefik's pod for CrowdSec, remove `403.html` from `edge/errors/html/errors/` so the image contains exclusively served error pages and twins.
  - Clean up inert `error_page 502/503/504` directives from `edge/errors/nginx.conf` in a future chore.
