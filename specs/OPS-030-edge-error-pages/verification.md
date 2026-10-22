---
tags: [spec, verification, templates]
created: "2026-10-16"
---

# Verification - OPS-030-edge-error-pages

## Evidence

| AC | Status | Proof |
|----|--------|-------|
| AC1, every errors page is reachable or declared | Met | #2360 (`1f0014cd`, 2026-10-17), `tests/test_error_pages_reachable.py` (13 passed, 1 skipped: `403.html`, the declared source page) |
| AC2, every IngressRoute carries `error-pages` or a reasoned exception | Met | #2361 (`ae331d1c`, 2026-10-17), `tests/test_error_pages_coverage.py` (6 passed); its body records a `make mutate` run that went RED when the vikunja base route lost the middleware. Exceptions live in `edge.errors.coverage.exceptions`, `infra/config/values/common.yaml` |
| AC3, five dead pages deleted, 403 kept | Met | #2360. `edge/errors/html/errors/` holds 403, 404, 502, 503, 504 and the four JSON bodies; `tests/test_error_pages_markup.py` (13 passed) and the reachability test hold the set |
| AC4, no-store, noindex, Retry-After, access_log | Met except access_log, which no test asserts | #2371 (`30d3be8c`, 2026-10-17), `tests/test_error_pages_nginx.py` builds and runs the image (20 passed, 0 skipped). `access_log` is on for `/errors/` by inheritance from `edge/errors/nginx.conf:22`; no test fails if that inheritance is broken; carried by #2617 |
| AC5, JSON by `Accept`, status unchanged | Met | #2371, `test_a_gateway_error_is_json_for_a_client_that_asks`, `test_everything_else_still_gets_the_page`, `test_the_catch_all_keeps_its_404_for_both_shapes` |
| AC6, prod routes without the middleware decided | Met | #2361: `authelia` (prod), `vikunja` and `n8n` UI carry `error-pages`; `argocd`, `loki`, `n8n` webhooks and `pr-agent` are exceptions with reasons. The decision is in #2361's body and ADR-072 decision 6, not as a comment on #1753 |

## Test status

- `poetry run pytest -q --no-cov tests/test_error_pages_reachable.py tests/test_error_pages_coverage.py tests/test_error_pages_markup.py tests/test_error_pages_nginx.py`: 52 passed, 1 skipped in 11.40s (2026-10-21, from the worktree root, Docker available).
- Issue #1753 (open): its h1, robots and orphaned-webp items landed in #2336 (`125f711b`, 2026-10-16) and #2346 (`348f5fd1`, 2026-10-16); the pages item in #2360. Nothing in it is outstanding.
- No regressions: this archive changes only the spec folder.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The decision per prod route followed the machine-client test of ADR-072: routes people open get the middleware, routes CLI and webhook clients call are exceptions with a reason.
- The ban page (ADR-072 phase 2) was kept out of scope and is #2368; `403.html` stays as its source.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/edge-tls/lesson-584-a-page-is-reachable-only-if-something-targets-it-and-a-test-must-say-what.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-072-edge-error-pages-brand-what-the-edge-generates.md
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: one project; the rule is recorded in ADR-072 and lesson-584

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OPS-030-edge-error-pages/` -> `specs/archive/OPS-030-edge-error-pages/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)

## Archive review dispositions (`agy/gemini-3.8-flash-high`, PASS WITH GAPS)

- Major (theoretical), no test asserts `access_log` on `/errors/`: ticketed as #2617 (OPS-044).
- Minor, lint and type findings in `tests/test_error_pages_nginx.py`: ticketed as #2621 (OPS-046); the tests directory is not linted (#1292).
- Minor, dead `error_page 502/503/504` in `edge/errors/nginx.conf`: ticketed as #2621 (OPS-046).
- Minor, the 403 page's JSON twin answers 404: owned by #2368 (ban page phase 2).
- Minor (theoretical), the middleware scan reads raw YAML instead of rendered overlays: ticketed as #2621 (OPS-046).
