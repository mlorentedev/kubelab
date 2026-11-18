---
id: adr-076-edge-backend-timeouts
type: adr
status: accepted
created: "2026-11-12"
owner: manu
---

# ADR-076: Bound how long the edge waits for a backend

## Status

Accepted 2026-11-12 (#3366), option A as proposed. Tracks #3076 (OPS-065). The values are chosen from the measurement in `specs/OPS-065-edge-backend-timeouts/verification.md` ("Measurement, prod, 2026-11-12").

## Context

Traefik 3.6 waits forever for a backend's response headers. `serversTransport.forwardingTimeouts.responseHeaderTimeout` defaults to `0`, and nothing in the repo sets it. A backend that accepts a connection and never answers holds every request sent to it. The per-host rate limiter (30/s, burst 150) bounds the rate, not how long each request stays open, so a stuck backend lets 30 more in each second, indefinitely. Traefik's memory follows in-flight requests (lesson-698), and one replica serves every route.

Three measurements decide the values. All were read from prod's slow-request access log (`make edge-slow-routes`, seven days, logged from 1 s):

1. **Few routes ever take long, and none of them took long to send its headers.** Across 13 routers, 6,484 requests took 1 s or more. Excluding Headscale, 15 took more than 10 s and 4 more than 30 s.
   - Gitea's three hour-long `GET 200`s and web's 34.6 s request are bodies after early headers, so a header bound does not cut them.
   - Uptime Kuma's three 10 to 13 s requests ended `499`: the client closed first.
2. **The access log is an upper bound.** `OriginDuration` includes the body copy, so a route under a bound is safe under it. A route over it needs its time to first byte measured before it is named as an exception.
3. **Headscale cannot be read from this log.** Its upgraded control connections are logged with status `0` and their whole life, up to 4.9 days. The log does not time the `101`.

## Options

A. **A default `responseHeaderTimeout` for every route, with named exceptions.** It is declared once in `common.yaml`, like `edge.errors.coverage.exceptions`. A test fails on an exception that matches no route.
B. **`inFlightReq` per host in the default middleware chain.** It caps how many requests a host may hold, not how long. A stuck backend still holds its share forever, and a legitimate burst is refused.
C. **Both.**

## Decision

1. **Option A, with a default of 60 s.** No route measured in seven days waited longer than that for its headers.
   - 30 s would also have cut nothing measured, but it leaves 5 s over socket.io's default 25 s long-poll interval (Uptime Kuma). Kuma's own setting was not read.
   - At 60 s, a stuck backend holds at most about 1,800 requests per host (30/s × 60 s), instead of an unbounded number.
2. **Headscale is an exception from the first deploy, until it is measured.**
   - Go's transport applies `ResponseHeaderTimeout` up to the `101`, so the handshake is probably far inside any bound. But Headscale is the bootstrap dependency of every node, and staging has no route to it, so a wrong guess would cost the VPN with no rehearsal.
   - The exception is lifted when a node re-registers in prod under the default (AC4).
   - It cannot outlive the work silently: AC4 is an acceptance criterion of OPS-065, so the spec does not archive while the exception stands. Keeping it past that point is a new decision, recorded here.
   - **Lifted 2026-11-14.** As first written, the condition cannot be met before the lift: a node cannot re-register under the default while the route still holds its exception. The lift is therefore verified by doing it. Before the lift, the default reached prod with the VPS provision, and ace2 re-registered through that edge while the exception still stood (#3493): the restarted edge and the 5 s dial bound both held. After the lift, ace2 re-registers under the default as soon as the change deploys, with the result recorded in the spec's `verification.md`. Rollback is reverting the lift, and existing connections are unaffected either way.
3. **`dialTimeout` 5 s, down from 30 s.**
   - Every backend is on the cluster network or the tailnet, so a dial that takes 5 s means the node is off.
   - On-demand routes then show their error page in 5 s instead of 30 s (#2207).
   - Not measured here. The owner may prefer 10 s.
4. **`idleConnTimeout` stays at its 90 s default.** Nothing measured argues for changing it.
5. **No `inFlightReq` now (option B is not adopted).** It refuses bursts that the duration bound does not. Reconsider it only if a stuck backend still costs memory with the bound in place.

## Consequences

- A backend that never answers gets the edge's 504 page after 60 s, instead of holding the request until the client gives up.
- A route that legitimately answers its headers later than 60 s, and was not in these seven days, will be cut. The coverage test and the declaration name it when it is found. Prod traffic is light, so a rare call may be missing from the sample.
- The rest of OPS-065's tasks follow from these values. The stuck-backend fixture and the staging check come first, then the prod deploy with the VPN check.

## Amendment 2026-11-15: the client side (EDGE-002, #3550)

This ADR bounded how long the edge waits for a backend. The edge also bounds how long it reads a request from a client, and nothing declared that bound. It is `entryPoints.<ep>.transport.respondingTimeouts.readTimeout`. It covers the whole request, body included, and Traefik v3 defaults it to 60 s.

**What it cut.** In prod Traefik's access log for the gitea router (2026-11-14):
- every failed registry push was a `PUT` ending in `499` at `total` ≈ 60 s from the request start (60.0 to 61.2 s);
- its paired 504s had `total` ≈ 60 s and an origin of a few µs.

A 499 reads as a client abort. Here it was the edge's own deadline.

**Decision.**

1. **Declare it at 60 s on `websecure`** (`k3s_traefik_websecure_read_timeout`, rendered into `additionalArguments`, asserted by `tests/test_edge_backend_timeouts.py`).
   - This is the value Traefik already applied, so the change does not alter behaviour. It makes the bound visible beside the backend bounds.
   - Owner ruling, 2026-11-14: raise it only on a measured off-LAN failure.
   - What it admits: a request body crosses it if the client sends at least about 7.5 MB per Mbit/s of uplink in 60 s (60 s × 1 Mbit/s ÷ 8). The 17 MB layer that exposed it needs about 2.3 Mbit/s sustained, which the home uplink did not give.
2. **It has no per-router form.** Any value applies to every route on the entrypoint.
   - Raising it for one upload raises it for every route, including how long a slow or idle client may hold a connection before sending its request.
   - The only finer alternative is a second entrypoint with its own bound. That is not adopted: no off-LAN upload is known to need longer.
3. **The failure that exposed it is fixed at its cause, not here.** Beelink CI pushed to the forge on the same node through the public edge. Jobs now push over the compose network (`KUBELAB_FORGE_REGISTRY`, `docs/runbooks/cicd.md`, lesson-762), so their blobs never reach this bound.

**Consequences.**
- An upload through the edge that takes more than 60 s is still cut with a 499: a large git push, an LFS object or a release asset from a slow link.
- A 499 at a round 60 s is this bound, not the client.
- Upgraded connections (Headscale's control channel, websockets) already ran under the same default, so declaring it changes nothing for them.
