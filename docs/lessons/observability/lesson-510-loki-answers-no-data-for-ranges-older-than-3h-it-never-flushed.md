---
id: lesson-510-loki-answers-no-data-for-ranges-older-than-3h-it-never-flushed
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: observability
tags: [kubelab, observability, loki, testing, alerting]
---

# A throwaway Loki answers "no data" for lines older than 3 h, whatever the querier flags say

**Context**: BACKUP-032 added a test harness that runs the pinned
`grafana/loki:3.6.4`, pushes fixture lines and evaluates alert rules from the
rules YAML. Cases share one Loki, so each takes its own time slot, and the
first version put the slots in the past.

**Problem**: The push answered 204, and every query, even `count_over_time` on
the stream just pushed, came back empty for any line more than 3 hours old.
The querier skips the ingester for ranges outside `query_ingesters_within`
(3 h), and the store is empty because nothing was flushed. Loki logged
`ingester_requests=0`. Neither `-querier.query-ingesters-within=0` nor
`-querier.query-ingester-only=true` (alone or with a long window) changed it in
3.6.4. An empty result is also the answer a broken rule gives, so the harness
was about to "prove" rules that never ran.

**Solution**: Put the slots in the future instead, and let Loki accept them:
`-validation.create-grace-period=8760h`. Every query window then ends after
"now - 3 h", so the querier asks the ingester. See `tests/loki_harness.py`.
The first harness test runs the existing `obs015-r2-backup-health` rule on a
healthy and an unhealthy fixture, so an empty-answering harness fails before
it judges anything new.

**Rule**: A harness that answers "nothing" must first prove it can answer
"something". Read a known rule both ways before trusting it on a new one. For a
throwaway Loki, timestamps in the future are queryable and timestamps in the
past are not.

**Tags**: `#loki` `#testing` `#alerting` `#harness`
