---
id: lesson-445-a-hint-guarded-by-a-bare-failure-names-a-cause-it-never-observed
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, drift-gate, spec-gate, false-diagnosis, pr-1427]
---

# A hint step guarded by a bare `failure()` names a cause it never observed — and a named cause gets acted on

**Context**: Triaging #1421, whose `Drift / staging` check went red. It was not drift. `poetry install` took a truncated download from PyPI:

```
IncompleteRead(7188772 bytes read, 3008073 more expected)
ProtocolError('Connection broken: ...')
##[error]Process completed with exit code 1
```

**Problem**: The drift step never ran, and the job then said:

```
##[error]Generator output drifted from committed files. Locally run:
##[error]  make config-generate ENV=staging
```

Both statements are false. The same merged tree gives `✓ No drift in staging generated configs`, exit 0. The `Hint on failure` step was guarded by a bare `if: failure()`, which is true when **any** earlier step in the job failed, so a network error in dependency installation was reported as a config-drift verdict with a remediation command — and the command was followed before the log was read. `spec-gate.yml` had the same shape with a worse sentence: a failed checkout would have announced that the PR closes a spec without archiving it.

This is the #1387 false-green family (lesson-391 is a neighbour) running in the other direction. Those controls could not distinguish "the thing is broken" from "I could not check" and always answered reassuringly. This one asserts a specific defect where none was observed — worse than silence, because it is actionable.

**Solution**: Each check step gets an `id`; each hint is conditioned on that step's own outcome (`steps.<id>.outcome == 'failure'`), not on the job's. Guarded by `tests/test_ci_hints_do_not_assert_a_cause.py`, demonstrated red against the previous workflows:

```
E  AssertionError: these steps diagnose a specific cause but fire on any job failure:
     check-config-drift.yml::drift-check::'Hint on failure'
     spec-gate.yml::spec-gate::'Hint on failure'
```

The guard carries a scan-sanity assertion so a moved workflows directory cannot turn it into a pass.

**Rule**: A message that names a cause must be gated on the step that observed that cause. `if: failure()` means "something in this job failed", and a hint hanging off it will eventually diagnose a network blip as the defect it was written for. Before following a CI remediation hint, read the step that actually failed — the hint is a claim, not evidence.

**Tags**: `#github-actions` `#drift-gate` `#spec-gate` `#false-diagnosis` `#ci-hints` `#pr-1427`
