---
id: "lesson-578-a-client-test-checks-its-requests-against-the-servers-own-swagger-not-a-fake"
type: lesson
status: active
title: "A client test checks its requests against the server's own swagger, because a fake certifies whatever it is asked"
created: "2026-10-16"
owner: manu
category: process-method
tags: [kubelab, process-method, testing, vikunja, contract]
---

# A client test checks its requests against the server's own swagger, because a fake certifies whatever it is asked

**Context**: `make sync-vikunja` had never created anything (#1701). Its reconciler called `GET /namespaces`, an endpoint Vikunja 1.0 removed, and the unit tests for `get_namespaces` and `create_namespace` passed for as long as the endpoint had been gone.

**Problem**: The tests mocked `session.request` and asserted on the URL the client built. A fake that answers whatever the client asks does not fail when the server stops answering: it certifies the endpoint it encodes (lesson-440). Nothing in the suite compared a request with what the server serves, so the 404 surfaced only when a real token finally reached the call, behind the 401 that had masked it (lesson-413).

**Solution**: Record the server's own path list once (`tests/fixtures/vikunja/swagger-paths-1.0.0.json`, from `/api/v1/docs.json`, which needs no credential) and let a test walk the client: it calls every public method with dummy arguments through a recording session, turns each URL into a swagger path template, and asserts the path exists with that verb. A removed endpoint, or a typo in a new one, fails the suite. `tests/test_vikunja_api_contract.py` is the pattern; a method added later is covered with no test edit, because the walk is by `inspect`, not by a list.

**Rule**: For any HTTP client the repo owns, derive the endpoints a test accepts from the server's published description, never from the client or a hand-written fake. Record the description at the version that is deployed and re-record it when the server is upgraded: the diff is the upgrade's change list. The swagger proves a route exists; it does not prove an API token may use it (Vikunja scopes tokens per route group), so that still takes one call by consequence.

**Tags**: `#testing` `#contract` `#vikunja` `#issue-1701`
