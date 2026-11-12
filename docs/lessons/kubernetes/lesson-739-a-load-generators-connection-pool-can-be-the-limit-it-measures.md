---
id: lesson-739-a-load-generators-connection-pool-can-be-the-limit-it-measures
type: lesson
status: active
created: "2026-11-12"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, load-test, k6, traefik, softirq]
---

# A load generator's connection pool can be the limit it measures

**Context**: Staging's warm knee was a line in three of three ramps: `api` `/health` degraded at 2,000/s and `web` `/` at 1,600/s (#3294). Every degraded step held k6's whole `maxVUs` pool (3,200 to 4,000 connections, left by the cold burst), and the node had cores to spare (#3308).

**Problem**: The pool k6 grows to (`max(200, 2 x rate)`) is a test setting, and it travelled with the rate: each step that offered more requests also held more connections. With the pool capped at 1,000 (`MAX_VUS=1000`), `api` was healthy at 3,200/s in all three ramps, twice the 1,600/s the uncapped runs reported as its last healthy step. `web` moved from 1,400 to 1,600 to 2,000/s, and its limit turned out to be one CPU of the node (`cpu2`, busiest in nearly every 2 s row), 97% busy at 2,000/s, about 60 points of it softirq.

**Solution**: A pool cap (`LT_MAX_VUS`, `make load-test MAX_VUS=...`) holds the connection count fixed across rates, and each timeline row names the busiest CPU with its busy and softirq shares. Run `2026-11-12-6fd47188`, report section "What limits warm capacity". A control on one build (`2026-11-12-bd7760cf-uncapped` and `-capped`, "Control on one build") reproduced both sets of knees, three of three each, so the pool and not the build moved them. The pool is not free for the edge either: without the cap, 4,000 open connections took Traefik past its 1,536 MiB limit and it was OOMKilled.

**Rule**: Before naming a server's limit from an open-model test, hold the generator's connection count fixed and see whether the knee moves. When a node with spare cores stalls, read per-CPU softirq before blaming the application: network work on one receive queue saturates one core while the node average looks idle.

**Tags**: `#load-test` `#k6` `#softirq` `#issue-3308` `#pr-3362`
