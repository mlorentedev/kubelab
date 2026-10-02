---
id: lesson-512-a-json-field-named-like-a-stream-label-is-renamed-and-the-grouping-moves
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: observability
tags: [kubelab, observability, loki, alerting, testing]
---

# A JSON field named like a stream label is renamed, and `by (<field>)` silently groups on the stream label instead

**Context**: BACKUP-032 (#485, #2037) added two Loki rules over the R2
watcher's `r2_backup_node` lines, grouped `by (node)`, where `node` is the
backup node each line reports on. The rules passed a test that evaluated them
in a real Loki against lines printed by the real probe (lesson-510).

**Problem**: In prod, Vector's Loki sink already sets a `node` stream label:
the K8s node the Job pod ran on (`vector-config/vector.yaml`). When `| json`
extracts a field whose name an existing label already has, Loki keeps the
label and renames the field to `node_extracted`. So `by (node)` grouped every
backup node into one series, keyed by the single VPS node. The shrink rule
divided the last line of a run (vps, 53 MB) by the first (beelink, 112 MB) and
read 0.477, under its 0.5 threshold. It would have paged from its first
evaluation, every time, and the freshness rule judged whichever on-demand line
came last. It was found minutes after merge by evaluating the rule against
prod Loki, before Grafana fired. The harness had pushed fixtures labelled only
`container` and `namespace`, so the collision could not happen there.

**Solution**: The rules extract the field under a name no stream label has,
`| json backup_node="node", metric="metric", ...`, and group
`by (backup_node)`. The harness takes its stream labels from Vector's sink
(`tests/loki_harness.py::stream_labels`), so it refuses a fixture missing one,
and it gives each probe its own `pod`, one stream per Job run as in prod. Two
tests use two backup nodes per run: a stale and a fresh on-demand node fire
only for the stale one, and nodes of different sizes never read as a shrink.
Both are red on the merged rules.

**Rule**: A test that runs a rule in a real engine is only as real as its
fixtures' shape. Take the stream labels from the shipper's config, never from
what the test author remembers. In LogQL, never group on a field extracted by
a bare `| json` when its name could also be a stream label: extract it under
its own name. A single-node fixture cannot show a grouping bug, so test with
at least two.

**Tags**: `#loki` `#logql` `#alerting` `#vector` `#testing` `#485`
