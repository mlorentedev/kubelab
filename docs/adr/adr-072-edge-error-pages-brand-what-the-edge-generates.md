---
id: adr-072-edge-error-pages-brand-what-the-edge-generates
type: adr
status: accepted
created: "2026-10-16"
owner: manu
---

# ADR-072: Edge error pages: brand what the edge generates, pass through what the app answers

## Status

Accepted — 2026-10-17 (first implementation, #2360, merged). Proposed 2026-10-16. Amends the scope of the `error-pages intercepts 502/503/504 ONLY` rule in `CLAUDE.md`; it does not reverse it. Tracks #1753 (OPS-030, UX-6).

## Context

`edge/errors` ships ten HTML pages (401, 403, 404, 408, 429, 500, 502, 503, 504, `maintenance`). An audit (#1753) found five of them unreachable. Measured on master, rendering both overlays with `kubectl kustomize`:

- The `error-pages` middleware intercepts `502-504` only. 502, 503 and 504 are reachable.
- 404 is reachable through the `catch-all` IngressRoute (unknown host → `errors` service → `location / { return 404 }` → `404.html`), in both environments.
- 401, 403, 408, 429, 500 and `maintenance.html` are referenced by nothing that targets them.

Three facts from the code decide the design. They were read from the source of the Traefik release K3s v1.34.4 bundles (chart 38.0.2, Traefik v3.6.6; source read at `v3.6.0`, `pkg/middlewares/customerrors/custom_errors.go`), not assumed:

1. **An intercepted response loses every upstream header.** `codeCatcher` buffers the caught response's headers in its own map and never copies them; the client receives the status code plus the headers of the error service. `Retry-After`, `WWW-Authenticate`, `X-RateLimit-*` and `Content-Type` of the app die on interception. This is the mechanical reason behind the existing rule, and it is correct.
2. **The request headers all reach the error service.** `utils.CopyHeaders(pageReq.Header, req.Header)` forwards `Accept` (which makes content negotiation possible) and also `Authorization` and `Cookie`. The `errorRequestHeaders` option that restricts this is not in `v3.6.0`.
3. **Traefik's own 429 carries `Retry-After` and `X-Retry-In`** (`ratelimiter/rate_limiter.go`), so intercepting it would drop the only machine-readable signal it has.

There is also no useful "web route vs api route" class in this fleet. Every UI host serves an API or a protocol on the same host (Gitea `/api/v1` and git smart HTTP, Argo CD grpc-web, Vikunja `/api/v1`, Grafana `/api`, Authelia `/api`, Open WebUI `/api/v1`, Uptime Kuma). A wide interception per host replaces those apps' JSON 403/404/500 with a generic page, and `Accept` negotiation does not save it: the body shape is the app's contract.

Finally, coverage is not blanket today: in prod `argocd`, `authelia`, `loki`, `vikunja` and `n8n` carry no `error-pages`, while staging `authelia` does. The hand-written manifests diverged from the generator and nothing noticed.

## Decision

1. **The class is who generated the error, not what kind of route it is.**
   - *Edge-generated* errors are branded: unknown host (404, done), upstream unreachable (502, 503, 504, done) and a CrowdSec ban (403).
   - *App-generated* errors (401, 403, 404, 408, 500 from the service) pass through untouched. The rule in `CLAUDE.md` stands; this ADR only states why.
   - *The one case this cannot separate:* the middleware matches by status, so an app that itself answers 502, 503 or 504 is indistinguishable from an edge-generated gateway error and is replaced by the branded page. That is accepted for the routes that carry the middleware (people-facing UIs); a route whose app uses those statuses as part of its contract is declared in `edge.errors.coverage.exceptions` instead (decision 6).
2. **429 stays unbranded.** The rate limiter's `Retry-After` is worth more to the machine clients that hit it than a page is to a human.
3. **Delete the pages nothing can reach by construction:** `401.html`, `408.html`, `429.html`, `500.html` and `maintenance.html`. `403.html` is kept as the source of the ban page (Phase 2), not served by the `errors` service.
4. **Content negotiation on the infra class.** The `errors` service answers `502-504` and the catch-all 404 with JSON when `Accept` prefers `application/json`, HTML otherwise, so an API client that gets a gateway error receives a machine-readable body instead of a page. The JSON shape is `{"error": {"status", "title", "message"}}`.
5. **Fix the response headers of the error service.** Error responses carry `Cache-Control: no-store` (today `/errors/` sends `public` with `expires 1d`, and that header reaches the client on every 502), `Retry-After` on 503 and 504, and `X-Robots-Tag: noindex`. `access_log` is on for `/errors/` so branded 5xx are countable in Loki.
6. **Coverage is enforced, not remembered.** A test renders both overlays and fails when an IngressRoute lacks the `error-pages` middleware and is not listed in `edge.errors.coverage.exceptions` in `infra/config/values/common.yaml`, with a reason per entry. Initial exceptions: `headscale` (Noise protocol), `catch-all`, `kubelab-redirect`, `brand-assets` and the webhook routes. Each existing gap (`argocd`, `authelia`, `loki`, `vikunja`, `n8n` in prod) is either fixed or declared with its reason in the same change.
7. **Reachability is enforced, and a declaration is not reachability.** A test asserts that every `errors/*.html` is targeted by a Middleware status range, by an nginx `error_page` for a status nginx can itself emit (derived from `nginx.conf`: `return NNN` and `try_files =NNN`, error statuses only), or is a declared source page. A bare `error_page` line for a status nothing can produce does not count: that is how 401, 408, 429 and 500 sat in the config. Measured on the built image, `/errors/`, `/errors` and unknown paths answer 404 and nothing answers 403, so `403.html` is a declared source page, not a served one.
8. **Phase 2 (separate PR): the ban page.** The CrowdSec bouncer plugin (v1.5.1) supports `banHTMLFilePath` and injecting a request header into the ban page. The branded 403 is delivered at the source, mounted into the Traefik pod through the Ansible-managed `HelmChartConfig`, with no interception and therefore no risk to app 403s.
9. **The `rate-limit` / `error-pages` order in the generator is not a constraint.** The comment "matches the VPS chain" in `generator_k8s.py` describes history; nothing in this design depends on the order.

## Consequences

### Positive
- The pages that remain are the pages that can be seen, and a test says which.
- API clients get a machine-readable gateway error and the cache defect on `/errors/` disappears.
- No app's error contract is touched, and the existing `CLAUDE.md` rule gains its mechanical justification.
- Coverage drift between hand-written and generated manifests becomes a CI failure.

### Negative
- Phase 2 changes the Traefik pod's volumes through Ansible, so it is the only part with operational risk.
- Traefik `v3.6` forwards `Authorization` and `Cookie` to the `errors` service. It is an in-cluster nginx that logs neither, but the option to restrict it exists only in a later Traefik; track it with the next K3s bump.
- A hand-written route added later needs an explicit decision (middleware or exception), by design.

## Alternatives considered

- **Delete everything unreachable and stop.** Correct on the narrow question, but leaves API clients with an HTML page on a gateway error, the cache defect and the coverage gaps.
- **Blanket `400-599`.** Replaces the JSON 4xx/5xx of every app with a generic page and drops `Retry-After` and `WWW-Authenticate`. Rejected by facts 1 and 3.
- **A `web`/`api` class per route in `common.yaml`.** The fleet has no such split (see Context), so the declaration would be wrong for most hosts.
- **Replace the nginx image with tarampampam/error-pages.** Adds an image and a pipeline for behaviours nginx provides in about twenty lines, and `/brand/` (ADR-071) lives in the same container.
- **Brand 429 with an outer middleware.** Loses `Retry-After`; rejected by fact 3.
