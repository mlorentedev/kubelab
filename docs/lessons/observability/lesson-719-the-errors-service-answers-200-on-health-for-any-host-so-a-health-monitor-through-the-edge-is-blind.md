---
id: lesson-719-the-errors-service-answers-200-on-health-for-any-host-so-a-health-monitor-through-the-edge-is-blind
type: lesson
status: active
created: "2026-11-06"
owner: manu
category: observability
tags: [kubelab, observability, uptime-kuma, traefik, errors]
---

# The errors service answers 200 on /health for any host, so a health monitor through the edge is blind

**Context**: During the 2026-11-06 Argo CD outage (lesson-717), every `argo.kubelab.live` path landed on the catch-all and the errors nginx, yet `https://argo.kubelab.live/healthz` answered 200.

**Problem**: `edge/errors/nginx.conf` declares `location /health { return 200 'OK'; }`, a prefix, so `/health`, `/healthz` and `/health/anything` answer 200 for every host the catch-all receives. Uptime Kuma's prod and staging API monitors were plain HTTP checks on `https://api.<env>kubelab.live/health`: had the API's route been lost, they would have stayed green. The n8n monitors were blind in a second way: `/healthz` sits behind the Authelia ForwardAuth, so they follow the 302 and read the portal's 200 (#3167).

**Solution**: Each monitor on a path the errors service answers itself is a keyword monitor on text only its service sends: `"service":"kubelab-api"` for the API, and Argo CD moved to `/api/version` with `"Version":"v`. `tests/test_uptime_kuma_edge_monitors.py` parses the 2xx locations out of the errors nginx config and fails on any `*.kubelab.live` monitor whose path one of them answers, unless it is a keyword monitor whose keyword the errors body does not contain.

**Rule**: A status code proves only that something answered. Behind a catch-all, check for text only the intended service produces, and derive the list of paths the fallback answers from its config rather than from memory.

**Tags**: `#uptime-kuma` `#errors` `#3156`
