---
id: lesson-737-a-rate-over-the-clients-clock-is-skewed-when-the-read-is-late
type: lesson
status: active
title: "A rate over the client's clock is skewed when the read arrives late; divide by the kernel's clock from the same read"
created: "2026-11-11"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, load-test, cgroups, ssh]
---

# A rate over the client's clock is skewed when the read arrives late; divide by the kernel's clock from the same read

**Context**: The load-test timeline (#3274) samples ace1 every 2 s over ssh: `/proc/stat` and the Traefik and target pods' cgroup `cpu.stat`, in one command. Node cores came from `/proc/stat`'s own jiffies; cgroup cores divided each `usage_usec` delta by the gap between the sampler's own stamps, taken before the read.

**Problem**: While ace1 was saturated, reads arrived 3 to 8 s apart and late by different amounts. The stamps and the counters then described different windows, and one row read Traefik at 5.56 cores on a 4-core node while another read the rest of the node at 3.0 (run `d46f3fbb`, #3102). Sums over a window were right, because counters telescope; single rows were not. The same sampler opened a new ssh connection per read, which cost ace1 a handshake every 2 s, on the node under test.

**Solution**: #3295. The cgroup cores divide by `elapsed_jiffies / ncpu / USER_HZ` from the `/proc/stat` read in the same command, so numerator and denominator share one clock and one window; guest time is left out of elapsed, since it is already inside user. The reads share one ssh master per node for the step (`ControlMaster=yes`, `-fN`, a `ControlPath` under `/tmp`, `-O exit` in a `finally`), with readers on `ControlMaster=no` so a master that failed to open degrades to direct connections. Measured at rest, six rounds of 30 s: ace1 at a median 0.300 cores without the sampler, 0.364 with a handshake per read, 0.305 over one connection; the node read fell from 0.60 to 0.13 s.

**Rule**: When a remote counter is turned into a rate, take the elapsed time from the same remote read as the counter, never from the client's clock around the request: under load the request's latency is what varies, and it lands in the denominator. A sampler that measures a saturated host should also not add a handshake per sample to it.

**Tags**: `#load-test` `#pr-3295`
