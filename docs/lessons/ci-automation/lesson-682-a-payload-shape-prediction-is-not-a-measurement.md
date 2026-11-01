---
id: lesson-682-a-payload-shape-prediction-is-not-a-measurement
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, evidence]
---

# A claim about a GitHub event payload is a prediction until a run of that event shows it

**Context**: #2656 gave `deploy-merge.yml` a job guard,
`github.ref_name == github.event.repository.default_branch`, to stop a dispatch on a feature
branch. Its only observed run was a dispatch on master.

**Problem**: Review raised that a `schedule` payload might carry no `repository`, which would make
the guard false and skip every cron sweep. No scheduled run had fired yet, since crons arrive hours
late here (lesson-681). #2888 scoped the guard to `workflow_dispatch` and wrote the prediction into
a code comment and a test docstring as fact. The first scheduled runs then landed on `8655ac26`,
which still carried the unscoped guard: runs 41240094141 and 41253974014 both executed the job, all
14 steps. So did the `workflow_run` runs under the same guard, for example 41224743030 on
`f40e9304`. Both payloads carry `repository`, so the skip never existed.

**Solution**: The scoped guard stays, because it is narrower and no worse. The comment and the
docstring were corrected to the measured behaviour, and #1619 records the measurement.

**Rule**: When a fix rests on how an event behaves that nobody has seen run, it may ship if it is
safe either way. Its comments, docstrings and commit text then state the claim as unmeasured, and
the first run of that event is checked before the claim is written as fact. A wrong comment
outlives the PR that wrote it.
