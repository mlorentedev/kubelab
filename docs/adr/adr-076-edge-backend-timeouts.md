---
id: adr-076-edge-backend-timeouts
type: adr
status: proposed
created: "2026-11-12"
owner: manu
---

# ADR-076: Bound how long the edge waits for a backend

## Status

Proposed 2026-11-12, for the owner's decision. Tracks #3076 (OPS-065). The values are chosen from the measurement in `specs/OPS-065-edge-backend-timeouts/verification.md` ("Measurement, prod, 2026-11-12").

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

## Decision (proposed)

1. **Option A, with a default of 60 s.** No route measured in seven days waited longer than that for its headers.
   - 30 s would also have cut nothing measured, but it leaves 5 s over socket.io's default 25 s long-poll interval (Uptime Kuma). Kuma's own setting was not read.
   - At 60 s, a stuck backend holds at most about 1,800 requests per host (30/s × 60 s), instead of an unbounded number.
2. **Headscale is an exception from the first deploy, until it is measured.**
   - Go's transport applies `ResponseHeaderTimeout` up to the `101`, so the handshake is probably far inside any bound. But Headscale is the bootstrap dependency of every node, and staging has no route to it, so a wrong guess would cost the VPN with no rehearsal.
   - The exception is lifted when a node re-registers in prod under the default (AC4).
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
