---
id: lesson-705-a-grafana-range-query-keeps-a-missing-series-alive-for-its-whole-range
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: observability
tags: [kubelab, observability, grafana, alerting]
---

# A Grafana range query keeps a missing series alive for its whole range, and a misspelled provisioning key changes nothing silently

**Context**: `obs015-pvc-unbound-failure` kept a deleted claim FIRING for about 90 minutes. That was measured under `noDataState: Alerting` (2026-09-05) and again, 89.5 minutes, under `OK` (2026-11-03). #1668 AC1 asks for one to two evaluation intervals (15m).

**Problem**: `noDataState` was never the cause, because other claims keep the result non-empty and the deleted claim's series goes *missing* instead. Two settings held it:

1. `queryType: range` with `relativeTimeRange.from: 1800` asks for 30 minutes of points, and each point has its own `[30m]` lookback. A series therefore stays in the result for 30 minutes past the lookback, and `reduce: last` keeps reading its final point.
2. Grafana keeps a missing series for 2 evaluations by default before resolving it.

The obvious fix has a trap. The API and its docs spell the setting `missingSeriesEvalsToResolve`, but Grafana 13.0.2 file provisioning reads only `missing_series_evals_to_resolve` (`pkg/services/provisioning/alerting/rules_types.go`). With the camelCase key in the file, Grafana provisions the rule without the setting and logs no error. The drill would then have measured 90 minutes again and blamed the idea.

**Solution**: Use `queryType: instant` and `missing_series_evals_to_resolve: 1`. Before using the staging slot, the change was verified on a local `grafana-oss:13.0.2`: the provisioning API read back `missingSeriesEvalsToResolve: 1` for the snake_case file and `null` for the camelCase one. On staging, `make drill-pvc-unbound` fired after 32.3m (unchanged). The claim was removed at 03:29:58Z, Grafana logged `Detected stale state entry` at 03:59:55Z, and the alert was gone at 04:00:05Z: 30 minutes, two intervals. `tests/test_pvc_drill.py::TestADeletedClaimResolvesPromptly` pins both settings and the spelling.

**Rule**: When an alert instance outlives its cause, find which state it is in (no data, missing series, or still matching) before choosing a setting. Then read a provisioned setting back from the running Grafana. A provisioning file accepts unknown keys, so only the read-back shows whether the setting took.

**Tags**: `#grafana` `#alerting` `#issue-1668`
