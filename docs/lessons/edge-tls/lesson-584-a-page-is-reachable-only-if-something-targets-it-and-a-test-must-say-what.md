---
id: lesson-584-a-page-is-reachable-only-if-something-targets-it-and-a-test-must-say-what
type: lesson
status: active
created: "2026-10-16"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, error-pages, traefik]
---

# A page is reachable only if something targets it, and a test must say what

**Context**: An audit of `edge/errors` (#1753) found five of ten branded error pages that no request could ever reach. The pages had been written, styled and unit-tested for markup, and for months nobody noticed that nothing pointed at them.

**Problem**: The `error-pages` middleware intercepts `502-504` only, and the 4xx/500 pages sat in nginx behind `error_page` lines that Traefik never asks for. Reading Traefik v3.6's `customerrors` source showed why the narrow range is right: an intercepted response loses every upstream header (`Retry-After`, `WWW-Authenticate`, `Content-Type`), and Traefik's own 429 carries `Retry-After`. The same audit found that five prod routes carry no `error-pages` at all, because hand-written manifests drifted from the generator. A test of the page's markup passes whether or not the page can ever be served.

**Solution**: Brand what the edge generates (unknown host, upstream unreachable, a CrowdSec ban), pass through what the application answers, and make both properties tests: every `errors/*.html` must be targeted by a Middleware status range, an nginx `error_page` or the catch-all, and every IngressRoute must carry the middleware or be declared an exception with a reason (ADR-072).

**Rule**: A file that ships in an image is reachable only if a generator or a route targets it, and a test has to name that target. Test reachability, not just content. When intercepting responses at a proxy, read what the proxy keeps of the original response before deciding which codes to catch.

**Tags**: `#error-pages` `#traefik` `#coverage-test` `#adr-072` `#1753`
