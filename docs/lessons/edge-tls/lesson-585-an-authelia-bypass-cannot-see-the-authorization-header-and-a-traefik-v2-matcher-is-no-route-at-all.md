---
id: "lesson-585-an-authelia-bypass-cannot-see-the-authorization-header-and-a-traefik-v2-matcher-is-no-route-at-all"
type: lesson
status: active
title: "An Authelia bypass cannot see the Authorization header, and a Traefik v2 matcher is no route at all"
created: "2026-10-17"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, authelia, traefik, grafana]
---

# An Authelia bypass cannot see the Authorization header, and a Traefik v2 matcher is no route at all

**Context**: hermes-kubelab needed to read Grafana's API with a service-account token. The ForwardAuth perimeter cannot carry a token, so #2369 added an Authelia `access_control` rule with `policy: bypass` and `resources: ['^/api/.*$']` for the host.

**Problem**: Two defects, one per layer.
- Authelia rules match on domain, path, method, network and subject. Not on headers. The bypass opened `/api/` to every caller on the public host, Basic credentials included, so the break-glass password could be tried without Authelia's regulation or 2FA. PR-Agent found it after the PR had merged.
- The fix, a Traefik route selected by `HeadersRegexp(`Authorization`, ...)`, copied the matcher from Loki's route. Traefik v3 renamed it `HeaderRegexp`; the v2 name parses only under `ruleSyntax: v2`, which nothing here sets. Measured on `traefik:v3.6` with two routers in a file provider: the `HeadersRegexp` one is `disabled` with `unsupported function: HeadersRegexp`, the `HeaderRegexp` one is `enabled`. Kustomize and every unit test render the v2 name without complaint, and the route simply does not exist. Loki's route has never worked (#2374).

**Solution**: Remove the Authelia rule. Add a prod Traefik route (priority 100) matching `Host && PathPrefix(/api/) && HeaderRegexp(Authorization, ^Bearer glsa_...$)` without the `authelia` middleware, beside the priority-50 route that keeps it (#2373). `tests/test_grafana_api_token_route.py` asserts that exactly one route skips Authelia, what it matches, that Authelia holds no bypass for the host, and that no manifest uses a v2 matcher. The parse was proven by running the real image and reading `/api/http/routers`.

**Rule**: A bypass that must depend on a header belongs in the proxy that can read headers, never in the IdP's rule list. And a matcher or rule syntax is verified by the component that parses it: a passing render says the YAML is valid, not that the router exists. Residual: Traefik matches a header if any of its values matches, so a second `Authorization` header can still select the token route; Grafana's lockout, the rate limit and CrowdSec bound it.

**Tags**: `#authelia` `#traefik` `#pr-2369` `#pr-2373`
