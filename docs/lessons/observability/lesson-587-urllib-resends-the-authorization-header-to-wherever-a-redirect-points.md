---
id: lesson-587-urllib-resends-the-authorization-header-to-wherever-a-redirect-points
type: lesson
status: active
title: "urllib re-sends the Authorization header to wherever a redirect points"
created: "2026-10-17"
owner: manu
category: observability
tags: [kubelab, observability, python, credentials, hermes]
---

# urllib re-sends the Authorization header to wherever a redirect points

**Context**: hermes-kubelab reads Grafana through a stdio MCP server written with the standard library. It presents a Viewer service-account token as `Authorization: Bearer glsa_...` on a single `urllib.request.urlopen` call.

**Problem**: `urlopen` follows a 3xx by default and rebuilds the request with the original headers, `Authorization` included, so the token goes to whatever host the `Location` names. The trigger was real, not theoretical: until the Traefik token route (#2373) existed, a Bearer request to `/api/` was answered with a redirect to the IdP before Grafana saw it, and the first live run would have sent the token along. PR-Agent found it in review; every test already written used a mocked `urlopen`, which never redirects, so none could have.

**Solution**: Install an opener whose `HTTPRedirectHandler.redirect_request` returns `None`, so a 3xx raises `HTTPError` and the reader reports `UNAVAILABLE (HTTP 302)`. `tests/test_hermes_grafana.py` proves it against two real local servers and asserts the redirect target is never asked; `make mutate` against the handler goes red.

**Rule**: A client that attaches a credential refuses redirects, or restricts them to its own host, and the test for it needs a server that actually redirects. A mocked transport cannot show that a header travels.

**Tags**: `#python` `#credentials` `#pr-2393`
