---
id: lesson-717-a-route-that-ties-the-catch-all-priority-works-until-traefik-restarts
type: lesson
status: active
created: "2026-11-06"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, traefik, argocd, incident]
---

# A route that ties the catch-all's priority works until Traefik restarts

**Context**: AUTH-020 (#3073) split Argo CD's IngressRoute in two: a redirect for an anonymous `/` at `priority: 100`, and a passthrough for everything else at `priority: 1`, added to make the order explicit. It fixed nothing: before #3073 the passthrough declared no priority, ranked 25 by its rule's length, and the redirect's 100 already outranked that. Prod also carries the `catch-all` IngressRoute, `HostRegexp(.+\.kubelab\.live)` to the errors service, at `priority: 1`.

**Problem**: The passthrough tied the catch-all. Which of two equal-priority routers wins is not something the configuration decides: it held for two days and flipped across a restart, which is all that was measured. Traefik restarted at 04:39 UTC on 2026-11-06, the tie fell the other way, and every Argo CD path except the anonymous `/` answered the errors service's 404. The hub was healthy throughout: `http://gcp1:30080/api/version` answered `v3.4.1` over the tailnet, and the errors nginx log showed the Argo CD requests arriving there. No alert fired, because a 404 is not a server error, and `/healthz` kept answering 200 because the errors nginx answers it too, so a probe on that path saw nothing wrong.

**Solution**: Drop the passthrough's explicit priority. Traefik then ranks it by the length of its rule (25), above the catch-all's 1 and below the redirect's 100. `tests/test_ingressroute_priority_over_catch_all.py` renders both overlays and fails on any rule whose effective priority (declared, else rule length) does not exceed the catch-all's. On the old manifest it names `argocd: Host(argo.kubelab.live) (priority 1)`.

**Rule**: A route's priority is relative to every other route on the entry point, not only to its sibling. Never declare a priority at or below a catch-all's. A tie is not a failure that shows up at deploy time: it shows up at the next restart, so check it in CI against the rendered overlay.

**Tags**: `#traefik` `#argocd` `#incident` `#auth-020`
