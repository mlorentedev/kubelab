---
id: "OPS-030-edge-error-pages"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-16"
issue: "mlorentedev/kubelab#1753"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "UX-6: closes #1753, deletes five dead pages and adds reachability and coverage tests; independent of the other active specs (owner authorized 2026-10-16) (17 active, limit 10, 2026-10-16)"
---

# OPS-030-edge-error-pages

## Why

<!-- from issue #1753: OPS-030: Error pages: no h1 on any page, no robots meta, and five branded pages Traefik never serves -->

Five of the ten branded error pages in `edge/errors` can never be served, an API client that hits a gateway error receives an HTML page, `/errors/` is served `Cache-Control: public` with a one-day `expires` (so the header reaches the client on every 502), and five prod routes carry no `error-pages` middleware at all. Nothing noticed any of it because no test says which page is reachable or which route is covered. ADR-072 records the decision; this spec implements it.

## What

After this work, the class of an error decides what the client sees (ADR-072): branded pages only for errors the edge generates, app errors pass through, and two tests fail CI when a page becomes unreachable or a route loses its middleware without a declared reason. Gateway errors and unknown hosts answer JSON to clients that ask for it. Error responses are never cached.

## Out of scope

- The CrowdSec ban page (ADR-072 phase 2): it changes the Traefik pod's volumes through Ansible and ships as its own PR under its own ticket.
- Branding 429 (rejected in ADR-072: it would drop `Retry-After`).
- Restricting the request headers forwarded to the error service: needs a Traefik newer than the v3.6 K3s bundles.
- Any change to what an application answers.

## Risks / open questions

- The `catch-all` route must keep returning 404 with the page body; the negotiation change must not alter its status code. Covered by AC5.
- Declaring an exception per route needs a reason; the prod gaps (`argocd`, `authelia`, `loki`, `vikunja`, `n8n`) each need an owner decision between "add the middleware" and "declare the exception". Argo CD and Loki serve CLI and machine clients, so adding the middleware there is likely wrong. Resolved in AC6 before code.
- The `errors` image changes: a `fix:` or `feat:` prefix is needed or release-please will not build it (CLAUDE.md).

## Acceptance criteria

- [ ] **AC1** A test fails when any `edge/errors/html/errors/*.html` is not targeted by a Middleware status range in `infra/k8s`, an nginx `error_page`, or the catch-all route.
- [ ] **AC2** A test renders both overlays and fails when an IngressRoute lacks the `error-pages` middleware and is not listed, with a reason, in `edge.errors.coverage.exceptions` in `infra/config/values/common.yaml`.
- [ ] **AC3** `401.html`, `408.html`, `429.html`, `500.html` and `maintenance.html` are deleted; `403.html` is kept as the source of the future ban page, and the reachability test knows it.
- [ ] **AC4** Error responses from the `errors` service carry `Cache-Control: no-store` and `X-Robots-Tag: noindex`; 503 and 504 carry `Retry-After`; `access_log` is on for `/errors/`. Verified by a request against the built image.
- [ ] **AC5** A request with `Accept: application/json` to a 502-504 error path and to the catch-all 404 receives a JSON body `{"error": {"status", "title", "message"}}` with the original status; any other `Accept` still receives HTML.
- [ ] **AC6** Every prod route without `error-pages` (`argocd`, `authelia`, `loki`, `vikunja`, `n8n`) either carries it or is an exception with a reason, decided by the owner before the code lands.

## References

- Bitácora board: #1753 (see the `issue:` frontmatter field)
- Related ADR: `docs/adr/adr-072-edge-error-pages-brand-what-the-edge-generates.md`, `docs/adr/adr-071-idp-branding-substrate.md`
- Lesson: `docs/lessons/edge-tls/lesson-584-a-page-is-reachable-only-if-something-targets-it-and-a-test-must-say-what.md`
