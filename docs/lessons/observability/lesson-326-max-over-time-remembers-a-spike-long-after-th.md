---
id: lesson-326-max-over-time-remembers-a-spike-long-after-th
type: lesson
status: active
created: "2026-08-14"
owner: manu
category: observability
tags: [kubelab, observability]
---

# `max_over_time` remembers a spike long after the value that caused it is gone — it silently defeats `for:`

**Context:** OBS-010 — two Grafana alert rules (`obs010-quota-requests`/`-limits`) on `kubelab` namespace memory utilization, `for: 5m` so the rules should only fire on a *sustained* breach, not a momentary one during a routine deploy restart.

**Problem:** the surge-drill acceptance criterion — a normal `make deploy-k8s` + rollout restart must NOT fire the alert — failed for real on its first live run. The query was `max_over_time({container="quota-watcher"} | json | unwrap pct [10m]) > 80`. That function returns the *peak* value observed anywhere inside the 10-minute lookback window, not the current value — so a single transient spike (the surge itself, ~88% for well under a minute) stayed visible to every evaluation for up to 10 minutes after the real value had already dropped back under 71%. `for: 5m` requires the query result to stay above threshold across multiple evaluations, but with `max_over_time` the *query result itself* is an artifact of window memory, not of present reality — the sustain check was satisfied by the window, not by anything actually sustained. Caught by watching the rule transition `inactive` → `pending` → **`firing`** live during the drill (a 15-minute background poll of the rules API), then cross-checking the raw Loki log lines directly and finding the real value had already recovered to 70.54% within 5 minutes — the rule was alerting on a ghost.

A second surprise on the same incident: restarting the Grafana pod (to deploy the `last_over_time` fix) did **not** clear the stale `firing` state — Grafana's alert state lives in its own database, not in-memory, so the pod restart was a no-op for the already-firing alert. It needed one more real evaluation cycle after the fix deployed to naturally resolve.

**Solution:** `sed -i 's/max_over_time(/last_over_time(/g'` on both rules — `last_over_time` reflects only the most recent sample in the window, so `for:` genuinely requires the underlying value to stay elevated across real evaluations, not just within one remembered peak. Locked in with a permanent regression test, `test_query_uses_last_not_max_over_time`, asserting the provisioned query string contains `last_over_time` and not `max_over_time`. Re-ran an identical drill afterward: same 88% peak, rule reached `pending` at worst, never `firing`.

**Rule:**
- **`max_over_time`/`min_over_time` over a window and a `for:` sustain check are two different memories of the same interval, and stacking them double-counts.** `for:` already provides "did this stay true across N evaluations" — feeding it a query that itself remembers the window's peak makes the alert fire on "was this ever true in the window", which is a much weaker, and often wrong, condition. Use `last_over_time` (or no windowing function at all, if the metric is already a point value) whenever `for:` is doing the sustain-detection work.
- **A passing static review of the LogQL expression would not have caught this** — `max_over_time` reads as the obviously-correct choice for "did utilization get too high," and only diverges from `last_over_time` under exactly the condition a surge drill creates. This is the same "exercised, not assumed" lesson OBS-009/IDP-031 already established for prod ordering claims, now shown to apply to alert *logic*, not just deployment state.
- **A restart does not clear alert state if that state lives outside the pod.** Don't treat "the fix is deployed" as "the symptom is gone" for anything with its own persisted state machine — wait for a real evaluation cycle and check the actual state transition, not just rollout status.

**Tags:** `#grafana` `#logql` `#alerting` `#obs-010` `#gotcha`

---
