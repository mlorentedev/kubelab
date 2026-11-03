---
id: load-test
type: runbook
status: active
created: "2026-11-02"
updated: "2026-11-02"
owner: manu
---

# Load test: measure staging's capacity

> OPS-054. Reports live in [`docs/load-test/`](../load-test/). The figures describe staging, never prod.

## Run it

```bash
make load-test ENV=staging
```

Needs ace1 and ace2 powered on, SSH to both and the staging kubeconfig. Takes up to an hour. Writes `docs/load-test/<date>-<commit>.json` (raw) and `.md` (tables). `REPEATS=`, `SECONDS=` and `MAX_RATE=` shorten it, and `MIN_RATE=` starts the ramp at a step, to rerun past a knee the ramp would otherwise stop at; a short run is a smoke test, so do not quote it. Any `ENV` other than `staging` is refused, and no option takes a URL.

Before it starts, avoid a staging deploy window: a pod replaced during a step marks the step `rollout`, and that ramp measures nothing. Rerun it.

## What it does

1. Checks the kubeconfig reaches exactly the staging node, and pulls the k6 image declared at `load_test.image` in `common.yaml` on ace2, recording its digest.
2. Baseline: 25 requests per second against each target through the real route, limiter included.
3. Applies `infra/load-test/limiter-bypass-route.yaml`, a route that only matches requests carrying `X-Load-Test: ops-054`, with the real chain minus `rate-limit`. The `rate-limit` Middleware is not edited and no other request bypasses it.
4. Ramps each target at 50, 100, 200, 400, 800, 1000, 1200, 1400, 1600, 2000, 3200 and 6400 requests per second, 60 s a step, 15 s apart, and stops at the first unhealthy step. Three ramps.
5. Deletes the route and the image, including when a step fails.

Results are written after the baseline and after each ramp, so a run that stops early keeps what it measured. Such a report opens with an "Incomplete" line, and its JSON carries `"incomplete": true`.

## Reading a verdict

Declared in `toolkit/features/load_test.py` before the first run:

| Verdict | Meaning | What the ramp's figure is |
|---|---|---|
| `latency`, `errors`, `throughput` | p95 over 250 ms, 1% errors, or under 95% of the requested rate | The knee |
| `generator` | ace2 over 85% CPU | A lower bound: the generator stopped first |
| `limiter` | A 429 on the bypass route | Nothing: the route was not in force |
| `rollout` | The pod changed during the step | Nothing: rerun |

`lower_bound_only: true` means do not call the figure a limit.

## If a run dies

A killed process skips the cleanup and leaves the route. `make test-infra` fails on it in `tests/infra/test_rate_limit.py`, because every route must carry the limiter. Remove it:

```bash
make load-test-clear ENV=staging
kubectl --kubeconfig ~/.kube/kubelab-staging-config get ingressroute -n kubelab load-test   # NotFound
```

The k6 image stays on ace2 in that case: `ssh ace2 docker image rm <the value of load_test.image>`.

## Rollback

Nothing to roll back between runs: the route exists only during a run, and its manifest sits outside `infra/k8s`, so no sync can deploy it.
