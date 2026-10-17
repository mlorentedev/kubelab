---
id: lesson-444-a-drill-that-asks-is-the-alert-firing-tests-a-level-when-the-property-is-an-edge
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: observability
tags: [kubelab, observability, grafana, alerting, drill, verification, exit-codes, pr-1654]
---

# A drill that asks "is the alert firing?" tests a level when the property under test is an edge — refuse before, rather than mis-attribute after

**Context**: #1646 gave the PVC-unbound drill its own teardown (lesson-429). Asked next to clear the ten-day-old residue in staging, the drill on master printed:

```
ac2-drill-unbound: residue from an earlier run is present -- absorbing it
ac2-drill-unbound: created; waiting up to 60m for the alert
PersistentVolumeClaim unbound or failed: FIRING after 0.0m (1 polls)
✓ ... fired and the claim is removed.
```

**Problem**: `FIRING after 0.0m`. The alert had been firing for ten days on the claim the drill absorbed one line above. It deleted that claim, created its own, polled once, saw an alerting instance with the right name, and reported success. The test appears to assert *"my claim made the alert fire"*; it asserts *"an alert with this name is firing"*. Level-triggered, where the property is edge-triggered. Attribution cannot be recovered afterwards: the instance is keyed by `(namespace, pvc)`, so a fresh claim under the same name **resumes** the existing alert — no `startsAt` advances, no label differs. Waiting for the old instance to resolve first would work, but that is 90 minutes (lesson-443) inside a command that already waits 45.

**Solution**: The drill checks the alert is **quiet before it creates anything**, and declines otherwise:

```
✗ Could not measure: the alert was already firing before this drill created
  anything, so a firing now proves nothing. This is NOT a failing rule.
```

`DrillResult.measured` carries it and the CLI exits **3**, deliberately not the **1** used for "did not fire": "I could not measure" and "the rule is broken" sharing an exit code would reproduce, in the instrument's own status, the collapse the command exists to remove (same reasoning as `toolkit obs alerts` refusing to render an unreachable Grafana as "no alerts"). Refusing to measure is not refusing to clean — the residue is still absorbed first. Mutation: disabling the precondition fails exactly the two tests that model the defect; a floor test, `test_a_quiet_start_measures_normally`, stops an unconditional refusal from passing them all.

**Rule**: When a check proves causation ("my action made X happen"), assert the edge, not the level: establish that X was *not* true before acting, or refuse to conclude. If a precondition fails, exit with a code distinct from the failure being tested for — an unmeasurable run and a failing run must never look alike to a script. Only a run against a system that already had the condition could expose this; reading the code, every unit test passed and the PR was reviewed.

**Tags**: `#grafana` `#alerting` `#drill` `#edge-vs-level` `#exit-codes` `#verification` `#pr-1654` `#1583`
