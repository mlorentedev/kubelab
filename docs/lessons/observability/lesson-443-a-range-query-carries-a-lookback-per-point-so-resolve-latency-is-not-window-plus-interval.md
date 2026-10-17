---
id: lesson-443-a-range-query-carries-a-lookback-per-point-so-resolve-latency-is-not-window-plus-interval
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: observability
tags: [kubelab, observability, grafana, alerting, loki, drill, hardcoded-numbers, pr-1667]
---

# A range query carries a lookback per point, so "window plus interval" is half the real resolve latency

**Context**: The PVC-unbound drill (`toolkit obs` drill, lesson-429) told the operator three times that the alert instance resolves "in roughly 30-45m" after the claim is removed. The figure was the arithmetic anyone would do from the rule: a `[30m]` window on a `15m` evaluation interval.

**Problem**: Measured on staging after a real drill run, one line per rule evaluation:

```
01:45:06  last disk_pvc_health line for the claim
02:14:55  evaluates, STILL SEES it -- inside the [30m] window
02:15     the series leaves the query result
02:29:55  first evaluation that cannot see it -> still FIRING
02:44:55  still FIRING   (45m in: the old advice said re-run about here)
02:59:55  still FIRING
03:14:55  RESOLVED
```

Ninety minutes, not forty-five. The rule uses `relativeTimeRange: from: 1800` with `queryType: range`, which is not one evaluation at a point: it asks for 30 minutes of points and **each point carries its own `[30m]` lookback**, so a single log line keeps producing points for a further 30 minutes and `reduce: last` takes the last one that exists. Only once the whole range is past that final point does Grafana's staleness handling (`noDataState: Alerting` on a vanished label set) start counting its intervals. Confirmed the series was gone rather than quiet by running the rule's expression as an instant query at 03:15Z: 9 series, all `healthy=1`, none the drill's claim.

The advice is acted on. Told 45m, the operator re-runs into a second refusal (#1654), and a drill that appears to fail twice reads as a broken drill, not as optimistic advice.

**Solution**: One constant, `RESOLVE_LATENCY_MIN = 90`, with the trace at its definition, quoted by all three messages. The test asserts on the **messages**, not the constant — a constant nothing quotes does not stop the next hardcoded number — and it reads the shipped source of both modules, because two of the three wrong figures lived in `cli/observability.py` rather than in the module the test imports. Mutation: reintroducing the old figure into the CLI message fails `test_no_message_carries_a_superseded_figure`.

**Rule**: Never derive an alert's resolve latency from the rule text; measure it once from the evaluation log and record the trace next to the number. A range query's effective lookback is window + range, not window. When a figure appears in operator-facing text, the guard belongs on the text that quotes it, scanning every module that renders a message, not on the constant.

**Tags**: `#grafana` `#alerting` `#loki` `#range-query` `#drill` `#hardcoded-numbers` `#pr-1667` `#1583`
