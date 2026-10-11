---
id: lesson-556-two-derivations-of-one-address-diverge-when-a-route-is-added
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, break-glass, open-webui, cors]
---

# Two derivations of one address diverge when a route is added

**Context**: The AI-009 break-glass drill. `make break-glass SVC=open-webui ENV=prod` printed `http://100.64.0.5:3080`. The operator signed in as `breakglass` and reached the admin UI, but no model answered.

**Problem**: Two pieces of code each derived "where break-glass reaches Open WebUI", and nothing compared them. The env file's `CORS_ALLOW_ORIGIN` admitted the redirect's declared `scheme://host:port`, which was `http://ace2.kubelab.internal:3080`. `break_glass.py` had used the same declared address until #2135 gave Open WebUI a public route. After that, the generic derivation took over: route, then a Service with no selector, then the EndpointSlice IP. The two were equal by coincidence and stopped being equal when an unrelated change landed. Open WebUI streams answers over socket.io, which refuses an origin outside the list (`... is not an accepted origin`), while `POST /api/chat/completions` still returned 200. So the failure looked like a model fault, not an access fault. The existing test asserted the origin list against the template's own inputs, so it pinned the bug in place.

**Solution**: #2202. The origin now comes from `tailscale_ip`, the key the EndpointSlice mirrors. `test_the_break_glass_way_in_is_an_origin_open_webui_accepts` renders the prod overlay, runs `break_glass.plan_access` on the committed Service and EndpointSlice, and asserts that the printed origin is in the rendered `CORS_ALLOW_ORIGIN`. It was red on master. `make mutate` on the EndpointSlice address also turns it red.

**Rule**: When two components each compute the same fact, test one against the other's output, not against shared inputs. A test that renders a template from the template's own variables proves only that the template renders.

**Tags**: `#break-glass` `#cors` `#ssot` `#issue-2202`
