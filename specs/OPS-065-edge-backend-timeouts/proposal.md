---
id: "OPS-065-edge-backend-timeouts"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-11-04"
issue: "mlorentedev/kubelab#3076"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "Debt from #3057 that changes every prod route; the operator approved exceeding the limit on 2026-11-04. Blocked on days of access-log data (#3106), so it adds a spec, not concurrent work. (14 active, limit 10, 2026-11-04)"
---

# OPS-065-edge-backend-timeouts

> **Naming**: file lives at `<repo>/specs/OPS-065-edge-backend-timeouts/proposal.md`. `OPS-065-edge-backend-timeouts` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #3076: OPS-065: Traefik never times out a backend's response headers, so a stuck backend holds requests until the edge runs out of memory -->

Traefik waits forever for a backend's response headers: `serversTransport.forwardingTimeouts.responseHeaderTimeout` defaults to `0` and nothing sets it, in either environment. The prod rate limiter bounds requests per second, not how long each stays open, so a backend that accepts connections and never answers keeps 30 more requests per second per host in flight, indefinitely. Traefik's memory follows in-flight requests (lesson-698), and one Traefik replica serves every route, so one stuck backend can take every route down with no load at all.

## What

- Traefik stops waiting for a backend's response headers after a declared default bound, and answers the client with the edge's error page instead of holding the request.
- A route that legitimately waits longer (a long poll, a stream, a webhook that does work before it answers) names its own bound and the measured reason, in one declaration in `common.yaml`, the same shape as `edge.errors.coverage.exceptions`.
- A test fails on a route that has neither the default nor a declared exception, and on an exception that matches no route.
- The same decision covers the rest of `forwardingTimeouts`: `dialTimeout`, whose 30 s default makes an on-demand route wait before its error page (#2207), and `idleConnTimeout`.
- An ADR records the values, the exceptions and why a duration bound was chosen over, or alongside, a count bound (`inFlightReq`).

## Out of scope

- Client-side timeouts (`entryPoints.*.transport.respondingTimeouts`): they bound slow clients, not stuck backends. A separate decision if the data shows a need.
- Rate limiting per host: unchanged. It stays the bound on request rate.
- A second Traefik replica: availability, not this defect.
- Measuring prod's capacity: #3103.

## Risks / open questions

- **What the access log measures:** Traefik's `OriginDuration` is the time around the whole proxying, body copy included (`pkg/middlewares/accesslog/field_middleware.go`, `AddServiceFields`, v3.6.7), not the time to the response headers that `responseHeaderTimeout` bounds. So the access log is an upper bound. A route whose requests always finish under a candidate bound is safe under it. A route with longer requests may be streaming a body after fast headers, or may answer its headers late; only a direct measurement (`curl -w '%{time_starttransfer}'` against the backend, or the backend's own timing) tells them apart, and only those routes need one.
- **Headscale (`vpn.kubelab.live`, prod only) is likely outside this bound, to verify:** its clients open the control protocol with an HTTP Upgrade (`/ts2021`), and Go's `Transport.ResponseHeaderTimeout` covers the wait until the `101`, after which Traefik copies the hijacked connection with no response timeout. Headscale is the bootstrap dependency for every node and its overlay is prod-only, so this is verified from its access-log lines (status 101, long `Duration`) and by re-registering a node after the prod deploy, not assumed. Its real exposure is to idle and client-side timeouts, which this spec does not change.
- **Routes that can answer their headers late:** those that do work before answering, such as n8n webhooks, Gitea operations, Grafana queries, the Argo CD API and Authelia. Argo CD's watch streams, Uptime Kuma's socket.io and Grafana Live send headers early and then stream, so the access log will show them long and the direct measurement will clear or list them.
- **The values are pending data.** The default and each exception come from the access log #3106 adds, collected in prod for at least seven days, plus the direct measurements above. Prod traffic is light, so a short window under-samples the rare long calls the bound would cut.
- **Mechanism:** the default is static config (`--serversTransport.forwardingTimeouts.*`), cluster-wide; an exception is a `ServersTransport` CRD referenced from the route's service. The declaration (`edge.backend_timeouts.exceptions`) stays the single source: both routes that use an exception are hand-written overlay manifests, so `tests/test_edge_backend_timeouts.py` holds each reference and `ServersTransport` to it, as `edge.errors.coverage.exceptions` does for error pages (amended 2026-11-12).
- **Duration and count bound different things:** a timeout cuts a hang; `inFlightReq` caps how many requests a host may hold. #3057 declined `inFlightReq` for a CPU ceiling, which is a different question. The ADR weighs both on this failure mode instead of carrying that verdict over.

## Acceptance criteria

- [ ] A test backend in staging that accepts connections and never answers is cut at the declared default bound, and the client gets the edge's error page within the bound plus a margin.
- [ ] A route declared as an exception keeps its longer bound, shown by the same backend through that route.
- [ ] `tests/` fails on a route with neither the default nor a declared exception, and on an exception that matches no route.
- [ ] Headscale ships as a declared exception (ADR-076 D2), the VPN keeps working after the prod deploy (a node re-registers, MagicDNS resolves), and the exception is then lifted and a node re-registers under the default. Amended 2026-11-12: the access log cannot time the `101` (upgraded connections are logged with status `0` and their whole life), so the handshake is shown by a re-registration, not read from the log.
- [x] An ADR records the default, the exceptions with their measurements, `dialTimeout` and `idleConnTimeout`, and the duration-versus-count decision.

## References

- Bitácora board: #3076
- Data source: #3106 (slow-request access log on the K3s edge)
- Related: #2207 (OBS-035, `dialTimeout` on on-demand routes), #3057 and lesson-698, lesson-708, ADR-072 (error pages), SEC-021 (no credentials in Loki)
