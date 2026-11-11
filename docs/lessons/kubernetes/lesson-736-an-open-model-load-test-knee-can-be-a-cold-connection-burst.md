---
id: lesson-736-an-open-model-load-test-knee-can-be-a-cold-connection-burst
type: lesson
status: active
title: "An open-model load test's knee can be a cold connection burst, not request capacity"
created: "2026-11-11"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, traefik, load-test, k6]
---

# An open-model load test's knee can be a cold connection burst, not request capacity

**Context**: The staging load test's first degraded rate moved between 1,000 and 2,000/s across runs with the same setup (#3102). The candidates were GC in Traefik, other pods on ace1, softirq or NIC interrupts, conntrack, and the generator. Per-step totals could not order them, so each step got a 2 s timeline (#3274).

**Problem**: None of the five was the cause. Every step, healthy or not, started with ace1 at 2.7 to 4.0 of its 4 cores, because k6 starts each step as a new process and every connection pays a TLS handshake. A step that settled within 4 to 6 s ran the rest of the minute at 0.5 ms on about 2 cores. A step that did not tipped over: k6's constant-arrival-rate executor added virtual users to hold the rate, each one opened another connection, and Traefik's CPU followed new connections rather than requests (4.63 cores at 439 requests/s while opening 855 connections, 1.95 cores at 1,500/s while opening 59). The climb stopped only at `maxVUs`. After it, every degraded step recovered to 0.5 to 1 ms at the same rate. So the "knee" measured how well the first two seconds absorb a cold burst, and which way those two seconds went decided the result.

**Solution**: Ruled out each candidate by the signal that would have shown it: GC at most 1.7 cycles/s, softirq 0.36 cores at onset, all four CPUs busy rather than one, nothing outside the Traefik cgroup beyond the steady-state 0.2 to 0.9 cores, conntrack at 14,506 of 131,072, generator at 51%. The finding is in `docs/load-test/report-2026-11-02.md`, "What starts the stall". #3294 splits warm request capacity from the cold-burst figure.

**Rule**: With an open-model generator (fixed arrival rate), latency at the start of a step makes the generator open connections, and on a CPU-bound TLS edge that is positive feedback. Before reading a fixed-rate test's first failure as capacity, look at what happens inside the step: a failure confined to its first seconds is connection setup. Report that number separately from warm throughput, since both are real, and only the second is "requests per second". Per-row CPU from a sampler whose reads stretch under load is skewed; quote time-weighted sums.

**Tags**: `#traefik` `#load-test` `#k6` `#issue-3102`
