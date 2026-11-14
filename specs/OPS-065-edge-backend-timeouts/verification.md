---
tags: [spec, verification, templates]
created: "2026-11-04"
id: "OPS-065-edge-backend-timeouts"
type: spec-verification
status: active
owner: manu
---

# Verification - OPS-065-edge-backend-timeouts

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 (default bound, edge's page): #3446 (`0eb9c828`). Measured in staging on 2026-11-13 against master, not a worktree deploy: the staging Application tracked `master` and was `Synced Healthy` at `0eb9c828`, and the provision ran from a master checkout at `bde7c201`. Measured after `make provision NODE=ace1 ENV=staging TAGS=k3s` (dry run `changed=1`, apply `changed=1`, re-run `changed=0`). Traefik's args carry `responseHeaderTimeout=60s` and `dialTimeout=5s`. `curl https://stuck-backend.staging.kubelab.live/` returned `504` after 61.29 s, and the body is byte-identical to `edge/errors/html/errors/504.html` (sha1 `8ff8d946…` for both).
- [x] AC2 (an exception keeps its longer bound): same run, `curl --max-time 90 …/exception` was still open when the client gave up at 90.01 s (`000`). The `stuck-backend-exception` ServersTransport is in the cluster.
- [x] AC3 (coverage test): `tests/test_edge_backend_timeouts.py`. `make mutate` turned it red three ways: an undeclared transport reference (2 failed), Headscale's `dialTimeout` 30s (1 failed), and the default argument removed from the template.
- [x] AC4 (Headscale): the default is in prod, Headscale ran on its exception until a node re-registered, and since #3503 it runs under the default, through which ace2 re-registered.
  - 2026-11-12: the prod sync of #3446 kept `vpn.kubelab.live` answering (`/key` 200 in 0.49 s, Argo CD `Synced Healthy` at `0eb9c828`).
  - 2026-11-14 provision. Each run came from a checkout even with master on everything Ansible renders: the apply at master `82b3f9d6`, the second run at `9c3ae6d9`, the rejoin at `0ad9cb11`. The commits in between touched only Beelink, Gitea and staging values. `CHECK=1` showed changed=2, the HelmChartConfig plus #3451's node maintenance script, which is unrelated and was pending on the VPS. The apply showed the same two, failed=0, and the second run changed=0. So both tasks are idempotent, the maintenance script included. The live Deployment carries `--serversTransport.forwardingTimeouts.responseHeaderTimeout=60s` and `dialTimeout=5s`; Traefik rolled out at 05:00:52Z.
  - After it: `vpn.kubelab.live/key?v=88` answered 200 in 0.49 s, and `make test-e2e ENV=prod` gave 73 passed, 20 skipped. These show no regression only. Neither exercises the bound: `/key` answers fast, and the timeout tests skip outside staging. What shows the default is in prod is the live args above. The bound's own behaviour is shown in staging (AC1). In prod Headscale still runs on its exception transport, so what the re-registration below exercises is the 5 s dial bound and the restarted edge, not the 60 s header bound. That bound reaches Headscale only when the exception is lifted, which the next entries record.
  - Re-registration: ace2 logged out over the LAN, then `make headscale-rejoin NODE=ace2` (single-use key, changed=2, failed=0). ace2 came back online at 100.64.0.5; `rpi4.kubelab.internal` resolved through MagicDNS; `tailscale ping rpi4` answered in 1 ms; SSH over the tailnet worked.
  - 2026-11-14, the lift: #3503 merged as master `8297a058`, removing the `headscale` entry from `edge.backend_timeouts.exceptions` and its ServersTransport. Argo CD synced prod in about 15 s. After it, no ServersTransport is left in `kubelab`, and the live `headscale` IngressRoute's service list is `[{"name":"headscale","port":8080}]`, with no transport of its own, so it takes the 60 s header and 5 s dial default. `vpn.kubelab.live/key?v=88` answered 200 in 0.57 s, and ace2 stayed online through the sync.
  - Re-registration under the default: ace2 logged out over the LAN again, then `make headscale-rejoin NODE=ace2` from a checkout at `8297a058` (changed=2, failed=0). It came back at 100.64.0.5; `rpi4.kubelab.internal` resolved through MagicDNS, `tailscale ping rpi4` answered in 1 ms, and SSH over the tailnet worked (07:26:44Z). This is the first `/ts2021` handshake measured through the bound: the upgrade's `101` came back inside it, and the upgraded connection outlives it, because the header bound ends at the `101`.
  - Five minutes later (07:31:51Z) every active peer was online: macmini, rpi3, kubelab-vps, ace1, beelink, gcp1, hermes-kubelab, rpi4. The offline ones were last seen days or months before the change (msi, jet1, Pixel, the old agent pod, aws1 tracked in #1573). `/key` still answered 200.
- [x] AC5 (ADR): `docs/adr/adr-076-edge-backend-timeouts.md`, accepted in #3366.

## Measurement, prod, 2026-11-12

`make edge-slow-routes` (prod, `BOUNDS` default 10 30 60), read 2026-11-12T07:15Z. The window is the whole of what Loki keeps (168 h): collection started 2026-11-05 06:50Z, so a later reading still covers seven days, not more.

Slow requests per router, last 7d (7 days with lines, the first 24 h ending 2026-11-06T07:14Z).
Logged from 1 s. Figures are `OriginDuration`, body copy included: an upper bound on the time to response headers.

| Route | Router | Slow requests | p50 s | p99 s | Max s | > 10 s | > 30 s | > 60 s | Statuses |
|---|---|---|---|---|---|---|---|---|---|
| headscale | 6dfdda17500288067526 | 5750 | 59.66 | 21748.36 | 423757.79 | 5737 | 5733 | 1652 | 0: 5750 |
| gitea | 4d0b79276f78ba8cd4d5 | 624 | 1.53 | 11.23 | 6872.69 | 10 | 3 | 3 | 200: 514, 201: 39, 202: 10, 303: 12, 307: 5, 400: 1, 401: 1, 404: 2, 405: 1, 499: 4, 502: 35 |
| web | 9a007d33a769b7b0fc2d | 37 | 3.21 | 25.55 | 34.63 | 1 | 1 | 0 | 200: 35, 404: 2 |
| uptime-kuma | cfb966f3460ba95592f2 | 26 | 1.37 | 12.2 | 12.93 | 3 | 0 | 0 | 200: 22, 499: 4 |
| console | de1e739a7da61fc7a0dc | 2 | 5.04 | 9.96 | 10.06 | 1 | 0 | 0 | 200: 2 |
| authelia | d2d89e983cbb8e0a6705 | 13 | 1.13 | 8.49 | 8.49 | 0 | 0 | 0 | 200: 10, 401: 3 |
| pr-agent | b8ca5cc79cfc56def65a | 4 | 4.98 | 4.99 | 4.99 | 0 | 0 | 0 | 200: 1, 499: 3 |
| vikunja | 99dc812966379464071a | 1 | 3.99 | 3.99 | 3.99 | 0 | 0 | 0 | 200: 1 |
| web | b84377b32c03221d65ce | 1 | 1.74 | 1.74 | 1.74 | 0 | 0 | 0 | 404: 1 |
| n8n | 972390681eb4f2395c4b | 14 | 1.17 | 1.36 | 1.37 | 0 | 0 | 0 | 200: 11, 201: 3 |
| open-webui | d15ae305feb6c0093d95 | 10 | 1.14 | 1.25 | 1.25 | 0 | 0 | 0 | 200: 10 |
| catch-all | 04e7d26d1992ca8f2146 | 1 | 1.14 | 1.14 | 1.14 | 0 | 0 | 0 | 404: 1 |
| grafana | 217f6c6a64b1707df579 | 1 | 1.03 | 1.03 | 1.03 | 0 | 0 | 0 | 302: 1 |
| api | | no sample | | | |  |  |  | |
| argocd | | no sample | | | |  |  |  | |
| brand-assets | | no sample | | | |  |  |  | |
| kubelab-redirect | | no sample | | | |  |  |  | |
| loki | | no sample | | | |  |  |  | |
| traefik-dashboard | | no sample | | | |  |  |  | |

Readings, per route past a candidate bound. The access log keeps no path (SEC-021), so a mechanism below is read from the route's backend and the line's status and duration, and is marked as inferred where no direct measurement was taken:

- **headscale.** Every line has status `0`, not `101` (5,750 lines). Each line is an upgraded control connection's whole life, from 1 s to 4.9 days. The log cannot time the handshake's `101`, so AC4 stays open. It needs a direct measurement of the `/ts2021` upgrade, or a node re-registering under the bound in staging, which has no Headscale route.
- **gitea.** Three `GET 200`s of 37, 98 and 115 minutes (ending 2026-11-06, 11-10 and 11-12). A 200 that lasts an hour is a stream, not a late answer: the headers came early and the body ran for the connection's life. Inferred: Gitea's server-sent events (`/user/events`) for an open tab, or a long git transfer. Seven lines between 10 and 30 s. Its 35 `502`s took 1 to 2 s and were answered through the error-pages service, so they are not a bound question.
- **web.** One `GET 200` of 34.6 s and one of 9.4 s from a static nginx site: body to a slow client. The headers are not late.
- **uptime-kuma.** Three `GET 499`s at 10.0 to 12.9 s: the client closed first. Inferred: socket.io long-polling, which holds the response (headers included) until there is data or its ping interval passes. That is the one route measured here whose headers can legitimately be late. It sits behind Authelia, so the direct measurement needs a session.
- **console.** One `GET 200` at 10.06 s. Behind Authelia; not measured directly.

What this does not show: routes with no slow request (`api`, `argocd`, `brand-assets`, `loki`, `kubelab-redirect`, `traefik-dashboard`) read as "no sample", not as "needs no exception". Prod's traffic is light, so a rare long call may not be in seven days.

## Test status

- Test suite: `make test` -> 10268 passed, 95 skipped (head of #3446 before its last merge of master)
- Staging: `make test-e2e ENV=staging` -> 68 passed, 23 skipped (2026-11-13, after the provision). This shows no regression only: the suite had no timeout expectation then. The next entry is the one that covers AC1 and AC2
- Staging, 2026-11-14: `tests/e2e/test_backend_timeouts.py` -> 2 passed in 136 s (again at 07:36Z, after the lift, with master at `8297a058`) (the default route answers the edge's 504 page at or after the declared bound; `/exception` is still open 15 s past it). Both read their values from the declarations: the bound from the `k3s_server` role defaults, the host from the fixture. `make mutate` raising the declared bound to 70 s turned the 504 test red (it got the 504 at about 60 s), so it checks the bound, not just the status
- No regressions in existing test suite: yes. One intermittent unrelated failure seen once and filed as #3445

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The task to measure time-to-first-header directly, for each route over the bound, was closed partly on inference. The independent review (2026-11-14) graded this a Major, THEORETICAL. Only Headscale's handshake was measured, by re-registering under the bound. For Gitea, uptime-kuma and console, "headers not late" is read from status and duration (see the readings above). The 5 s dial bound is not measured (ADR-076 D3). The edge's own log is the check. A route cut at the header bound logs a `504` near 60 s, and one cut at the dial bound logs a `504` near 5 s. The first read after the deploy found 0 `504`s on any router, 2026-11-14 05:00Z to 07:55Z. The 7 `502`s in that window were Headscale's, at 06:37Z, before the lift, and took under 1 ms, so they were not cut by a bound. A week's read is #3520.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/gitops-delivery/lesson-743-a-new-kind-reaches-argo-cd-only-after-register-spoke.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-076-edge-backend-timeouts.md
- [x] New pattern candidate for `00_meta/patterns/`? no: the bound and its exceptions are specific to this edge; nothing like it exists in another project yet

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OPS-065-edge-backend-timeouts/` -> `specs/archive/OPS-065-edge-backend-timeouts/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
