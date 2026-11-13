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

Needs ace1 and ace2 powered on, SSH to both and the staging kubeconfig. Takes up to an hour and a half (the warm-up adds half a step). Writes `docs/load-test/<date>-<commit>.json` (raw) and `.md` (tables); a rerun on the same day and commit gets `-2`, `-3` and so on, never replacing an earlier run. `REPEATS=`, `SECONDS=` and `MAX_RATE=` shorten it, and `MIN_RATE=` starts the ramp at a step, to rerun past a knee the ramp would otherwise stop at; a short run is a smoke test, so do not quote it. `ACCEPT_ENCODING=identity` replaces k6's default `Accept-Encoding: gzip`, for an A/B on a server that compresses per request (web#615); the result's `facts.accept_encoding` records which. Any `ENV` other than `staging` is refused, and no option takes a URL.

Before it starts, avoid a staging deploy window: a pod replaced during a step marks the step `rollout`, and that ramp measures nothing. Rerun it.

## What it does

1. Checks the kubeconfig reaches exactly the staging node, and pulls the k6 image declared at `load_test.image` in `common.yaml` on ace2, recording its digest.
2. Baseline: 25 requests per second against each target through the real route, limiter included.
3. Applies `infra/load-test/limiter-bypass-route.yaml`, a route that only matches requests carrying `X-Load-Test` with a value drawn for this run, with the real chain minus `rate-limit`. The value is rendered over the manifest's placeholder, applied from stdin and recorded nowhere, so a route a dead run leaves behind bypasses nothing anyone can send; the next run's apply replaces it (#3012). The `rate-limit` Middleware is not edited and no other request bypasses it.
4. Ramps each target at 50, 100, 200, 400, 800, 1000, 1200, 1400, 1600, 2000, 3200 and 6400 requests per second, each step a 30 s warm-up then 60 s judged, 15 s apart, and stops at the first step unhealthy after its warm-up. Three ramps.
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

**What the knee measures.** Each step starts k6 fresh, so every connection is new, and a fixed-rate generator answers a slow start by opening more of them. Since #3294 each step opens with a warm-up (`WARMUP_SECONDS`, 30 by default, `criteria.warmup_seconds`) on the same virtual users, and every request is tagged `cold` or `warm` by when it was sent. The verdict, the step's figures and `knee` read only the `warm` requests: that is request capacity with connections open. The warm-up is judged by the same limits and kept as the step's `cold` figures, `cold_reasons` and the ramp's `cold_knee`: how much connection setup of a cold burst ace1 absorbs (most likely TLS handshakes; not profiled), whose production analogue is every client reconnecting after a Traefik restart or a deploy. Quote both, named. `status_429`, `dropped`, `vus_peak`, the generator's CPU and the edge and pod checks are not tagged per request, so they stay step-wide: `vus_peak` includes the burst. Before quoting the warm figure, check in the step's `timeline` that the rows after the warm-up are flat in `open_connections` and `edge_rps`; if they still climb, the warm-up was too short for that rate. With `WARMUP_SECONDS=0` a step reads as it did before #3294, and runs before it have no `cold` figures: their knee is the cold one (#3102, lesson-736).

`MAX_VUS=` caps k6's pool (`criteria.max_vus`; unset, twice the rate). k6 never closes a connection it opened, so without a cap a step that failed its burst runs warm with the whole pool open. A cap below what the burst would open holds the warm phase at that many connections, so a degraded warm step can be told apart by connection count or by rate (#3308). The burst then drops arrivals and reads as cold `throughput`; that is the cap, not ace1.

These flags qualify both `knee` and `cold_knee`. `lower_bound_only: true` means do not call the figure a limit. `measured: false` means there is no figure at all (a `limiter` or `rollout` stop, or the generator saturating on the first step), and every figure beside it is null. `measured: true` with a null `last_healthy_rps` means the service degraded on the first step: the knee is below `first_degraded_rps`. Runs before #3012 have no `measured` key and read `lower_bound_only: true` in that case too.

Below each ramp, "Where the time went" splits every step by k6's request phases (p95 and p99, in ms). The latency columns above are `http_req_duration`, which leaves out `blocked`: a step whose p99 is low while `blocked` or `connecting` is in seconds waited for connections, not for the backend. A high `waiting` points at Traefik or the backend instead. The phases are in each step's `phases` field in the JSON; runs before #3102 have none.

Each step also carries a `timeline` in the JSON: one row every `SAMPLE_SECONDS` (2 by default, `facts.sample_seconds`; `SAMPLE_SECONDS=0` turns it off), with the three sources read at once and rates over the measured interval; a read slower than the interval (a node read takes about 0.13 s at rest and several seconds when ace1 is saturated) stretches that row, not the next, so what moved first inside a degraded step can be read rather than guessed from its totals (#3102). A row holds Traefik's request rate and mean latency on `websecure`, its open connections, CPU, GC cycles per second, stop-the-world time and allocation rate; the node's busy and softirq cores, its busiest single CPU (`max_cpu`, its busy share and its own softirq share: softirq on one core is a network queue, busy without it is work) and its conntrack count; the Traefik and target pods' cgroup cores and what the rest of the node used; and ace2's CPU. `t` counts from when sampling began, about two seconds before k6 does, and sampling runs ten seconds past the step, so the rise and fall of `edge_rps` mark where k6 ran. A row without some fields means that read failed, and `edge_reset: true` means Traefik restarted between two samples. Everything is read: Traefik's metrics through the apiserver's pod proxy, the rest from `/proc` and the pods' `cpu.stat` over ssh. It cannot see concurrent GC mark CPU (this Traefik exports no `go_cpu_classes_*`), and each sample costs the apiserver on ace1 one small request. The two ssh reads share one connection per node for the step (a master under `/tmp`, closed when the step ends; a master that fails to open leaves direct connections). Measured at rest on 2026-11-11, six rounds of 30 s, median ace1 cores: 0.300 without the sampler (range 0.270 to 0.462), 0.364 with a handshake per read (0.352 to 0.404), 0.305 over one connection (0.296 to 0.338), so its cost is now within the spread of the node at rest; the node read's median fell from 0.60 to 0.13 s. The cgroup cores divide by the wall time `/proc/stat` counted in the same read, not by the gap between sample stamps, so a late read no longer shifts CPU between rows (#3295). The cgroup files are still read a few milliseconds after `/proc/stat`, inside the same command, so the rest of the node (`other_cores`) can read slightly below zero; it is reported with its sign rather than clamped, and a small negative figure is that skew, not a fault.

## If a run dies

A killed process skips the cleanup and leaves the route. `make test-infra` fails on it in `tests/infra/test_rate_limit.py`, because every route must carry the limiter. Remove it:

```bash
make load-test-clear ENV=staging
kubectl --kubeconfig ~/.kube/kubelab-staging-config get ingressroute -n kubelab load-test   # NotFound
```

The k6 image stays on ace2 in that case: `ssh ace2 docker image rm <the value of load_test.image>`.

## Rollback

Nothing to roll back between runs: the route exists only during a run, and its manifest sits outside `infra/k8s`, so no sync can deploy it.
