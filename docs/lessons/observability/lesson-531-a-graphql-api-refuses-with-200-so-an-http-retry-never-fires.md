---
id: lesson-531-a-graphql-api-refuses-with-200-so-an-http-retry-never-fires
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: observability
tags: [kubelab, observability, n8n, cloudflare, graphql, retry]
---

# A GraphQL API refuses with 200, so an HTTP retry never fires

**Context**: The first scheduled run of the moving-sale digest (`sale-metrics-daily-digest`,
APP-CONFIG-018) arrived on 2026-10-07 with "Visitas web: No disponible". A manual run at 07:56
the same morning had answered.

**Problem**: Cloudflare's GraphQL Analytics API refused the whole query with
`serviceUnavailable` ("unable to execute query, please try again later"), `data: null`. It
does that with HTTP 200, as GraphQL reports every failure in the body. The node's `retryOnFail`
reacts to node errors only. A 200 is not one, and with `neverError` on the request nothing is.
So the node had no retry it could use. The digest named the failure, as designed, and lost
the day's main figure to a transient error.

**Solution**: The retry is in the graph, not in the node. An IF node (v2 filter shape, lesson-467)
tests the answer: `errors` non-empty, or no `data.viewer`. Its true branch goes to a 60 s Wait
and an identical copy of the request, "Web Analytics, second try". Both branches feed the
Code node, which reads the second answer when it exists:

```js
const webNode = $('Web Analytics, second try').isExecuted ? 'Web Analytics, second try' : 'Web Analytics, last 24 h';
```

`$('<node>').first()` throws on a node that did not run on this branch; `.isExecuted` does not.
The test stand-in for `$` now refuses names no workflow node has and `first()` on a node that
did not run, as n8n does, and the IF's real expression is evaluated against the answer
Cloudflare gave (`tests/test_n8n_sale_digest.py::TestWebAnalyticsIsAskedTwice`).

**Rule**: Retry a GraphQL (or any 200-with-`errors`) call by testing the body and branching back
to a copy of the request. A node-level retry only fires on node errors, and a GraphQL refusal
is not one. Keep the Wait under 65 s, so n8n holds the execution in memory instead of parking
it in the database.

**Tags**: `#n8n` `#graphql` `#cloudflare` `#retry`
