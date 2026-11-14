---
id: lesson-747-a-pin-gated-app-needs-a-fallback-route-until-its-first-pin
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, routing, console, pr-3443]
---

# Registering an app that is deployed only with a pin leaves its host unrouted until the first pin, so what the host served before has to keep serving

**Context**: ADR-074 step 3 puts the console frontend (`apps/console`) on the console host, which until then was served whole by the API's embedded page through a hand-written IngressRoute. Since #3456 a platform app with no `apps.platform.<app>.version` in an env is not emitted there: no Deployment, Service, route or ConfigMap. The frontend's routes are generated, so they exist only once an env pins a version.

**Problem**: Three things fail together if the hand-written route is simply replaced. The generated route is named `console`, like the hand-written one, and kustomize refuses two objects with one id. Deleting the hand-written route clears that, but prod has no console pin until a `console-vX.Y.Z` release exists (the registering change is `chore`, which cuts none), so `console.kubelab.live` would have had no route at all while the embedded page was meant to live on. And the prod patch that targets the route by name would have pointed at nothing, a render error. None of it shows in a unit test of the generator: the generated overlays are identical to master's until a pin exists.

**Solution**: Rename the hand-written route `console-embedded` and give its one rule `priority: 10`. Traefik ranks a rule without an explicit priority by the length of its match, so every generated rule on the host (the `/console/` one at 100, the bare `Host()` one at its 28 or more characters) outranks it, while the edge's catch-all to the errors service (priority 1) is below it. The first version said `priority: 1`, the obvious "lowest" value, and `tests/test_ingressroute_priority_over_catch_all.py` refused it: a tie with the catch-all is broken by router name, and lesson-717 is the prod outage that came of one. With a pin, the generated routes serve the host; without one, the fallback serves exactly what the host served before. `tests/test_console_route_auth.py` renders the generated route with a pin the committed config does not have yet and asserts the fallback loses on every path, so the first deploy pull request cannot invert it. The fallback is deleted with the embedded page.

**Rule**: When a change registers an app whose manifests only exist with a pin, list every object that served the app's host or name before and keep it until the first pin lands. Make the older object lose by priority, not by deletion, and place it strictly between the other rules it can tie with and the ones it must lose to (not at the floor), and test the ordering against the state that does not exist yet (a pin supplied by the test), not only against the committed overlay.

**Tags**: `#routing` `#console` `#pr-3443`
