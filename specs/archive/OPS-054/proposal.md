---
id: "OPS-054"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-11-01"
issue: "mlorentedev/kubelab#2956"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator directed this ticket for tonight's unattended run; no other spec is being worked in this session (14 active, limit 10, 2026-11-01)"
---

# OPS-054

> **Naming**: file lives at `<repo>/specs/OPS-054/proposal.md`. `OPS-054` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

mlorente.dev is being rewritten for SRE and platform readers (mlorentedev/web#499), and no load, concurrency or latency figure about KubeLab has a method behind it. The only evidence is `ab -n 300 -c 100` from 2026-08-15, which measured SEC-004's rate limiter. A figure that will be quoted publicly needs a repeatable method, and an honest small number is worth more than an impressive shaky one.

## What

`make load-test ENV=staging` measures staging and writes dated results. k6, pinned, runs on ace2 against ace1 over the LAN: a baseline under the limiter, then ramps of fixed arrival rate that stop at the first degraded step, with node and pod figures around each step. Any other env is refused, no command takes a URL, and the run removes what it applied.

## Out of scope

- Any load against prod, and any statement about prod's capacity.
- Endpoints that write or call third parties (`/subscribe`, `/ready`): only `api /health` and `web /`.
- Authenticated flows (Authelia, Grafana), the database, and sustained soak or failure injection.
- Changing the limiter's values or the Prometheus question.

## Decisions

- **Generator on ace2.** From the Mac the path is a DERP relay (31 ms); ace2 is 0.45 ms away at 1 Gbit/s. A generator on ace1 would compete with what it measures.
- **The limiter is not edited; a run-scoped route bypasses it.** Rejected: relaxing the `rate-limit` Middleware, which Argo CD reverts when master moves (lesson-330) and which is shared by every route; repointing staging at this branch, which holds the shared slot, stops staging receiving master, and if the session dies leaves it there; a permanent exempted route, which would add the first exception to SEC-004's "every route carries the limiter". `infra/load-test/limiter-bypass-route.yaml` is header-scoped, lives outside `infra/k8s` so no overlay can sync it, applied at the start of the ramps and deleted in a `finally`. `alert-smoke` is the precedent for a throwaway IngressRoute in staging. If a run dies, `tests/infra/test_rate_limit.py` fails on the leftover and `make load-test-clear` removes it.
- **Open model.** Fixed arrival rate, so a slow server cannot slow the generator and hide its own latency.
- **Degradation is declared in code before the first run**: 1% errors, p95 over 250 ms, or under 95% of the requested rate. A 429 on the bypass or a replaced pod invalidates the step; a generator over 85% CPU makes the result a lower bound.

## Risks / open questions

- A staging rollout during a step corrupts it. Detected by pod identity; the ramp is rerun.
- ace2 may saturate before ace1. Detected by its CPU; the figure is then a lower bound.

## Acceptance criteria

1. The test lives in the repo, runs with one documented command, and is pinned.
2. It targets staging only and refuses production hostnames by construction.
3. It records latency percentiles, error rate, throughput, and the concurrency at which the service degrades, with node resource use during the run.
4. Staging's rate limiter is handled through a declared, reversible configuration, not a manual change, and the method states what was changed.
5. Results are committed with date, commit, hardware and method.
6. The report says how far staging differs from production, so the figure is not read as production capacity.
7. Defects found are fixed or ticketed with their root cause.

## References

- Bitácora board: mlorentedev/kubelab#2956
- Runbook: `docs/runbooks/load-test.md`
- Related: SEC-004 (`specs/archive`), lesson-330, ADR-037
