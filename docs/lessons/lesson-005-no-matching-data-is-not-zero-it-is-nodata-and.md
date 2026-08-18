---
id: lesson-005-no-matching-data-is-not-zero-it-is-nodata-and
type: lesson
status: active
created: "2026-08-10"
owner: manu
tags: [kubelab, lesson]
---

# "No matching data" is not zero — it is NoData, and the default acts on it

**Context**: OBS-007 phase 2/3. A Grafana alert rule over a Loki query that counts ACME failures in Traefik's logs. The healthy state is "no failures", which felt like it should evaluate to zero.

**Problem**: It does not. `sum by (domain) (count_over_time({...} |~ "..." [10m]))` over a selection that matches nothing returns **no series at all**, not a series with value 0. Grafana therefore evaluates the rule as **NoData**, and Grafana's default `noDataState` is to alert on it.

Left at that default, this rule would have fired continuously in prod *while certificates were renewing perfectly*, and it would have fired into the `page` tier. The inversion is total: the alert would be loudest exactly when nothing was wrong, which is the fastest way to get an alert channel muted permanently.

This was confirmed in production rather than reasoned about. Every prod evaluation logs `framesLength=0`, because prod has no ACME failures.

**Solution**: `noDataState: OK` on any rule whose healthy state is an empty result set — which is every log-matching alert, as opposed to a metric-threshold alert where the series exists continuously and only its value moves. Give it its own test; it is one word in a manifest and it inverts the entire behaviour of the alert.

**Rule**: Before writing the condition, ask **what the query returns when everything is fine**. That question — not the query's type — decides `noDataState`:

- Healthy result is **empty** (alerting on the *presence* of bad lines: errors, failures, rejections) → NoData is the healthy state → `noDataState: OK`. This rule.
- Healthy result is **non-empty** (alerting on the *absence* of expected lines: a missing heartbeat, a job that stopped reporting) → NoData is precisely the failure → leave it alerting, and `noDataState: OK` would blind you to the exact outage you built it for.

Both are log-based alerts, and they need opposite settings, so "log query" is not the discriminator. Getting it backwards is silent in both directions: one alerts forever while healthy, the other stays quiet through the outage.

**Corollary on proving a negative.** The criterion "the rule must not fire on the periodic heartbeat" was written as "leave it enabled across at least one heartbeat and confirm it stays Normal". That is the weaker test: it shows the rule was quiet, without ever establishing that a heartbeat was inside an evaluated window — 24 hours of silence over an absent input proves nothing. Constructing the case is stronger and instant: evaluate the alert expression at a timestamp one minute *after* a known heartbeat, so the heartbeat is provably inside the `[10m]` range, then assert the result is empty. Prefer constructing the condition you want to disprove over waiting for it to occur.
