---
id: lesson-441-a-reusable-workflow-has-no-runs-so-a-watcher-pointed-at-one-is-red-forever
type: lesson
status: active
created: "2026-09-06"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, reusable-workflows, observability, specs]
---

# A reusable workflow has no runs of its own, so a monitor pointed at one is red forever — and the ticket said to point one at it

**Context**: `#1682` closed `#1666`'s AC3: nothing reads `conclusion ==
startup_failure`, the one verdict that reports itself nowhere. Its AC1 named the
five workflows to watch — `staging-deploy.yml`, `web-image-receiver.yml`,
`promote-prod.yml`, `release.yml`, and `ci-publish.yml` — and a companion AC3
required that "never run" be reported distinctly from healthy, because absence of
a run is not evidence of health.

**Problem**: Those two criteria contradict each other, and only measurement says
so. Asked before writing any code:

```
$ gh api "repos/O/R/actions/workflows/<file>/runs?per_page=1" --jq .total_count
staging-deploy.yml       17
web-image-receiver.yml  129
promote-prod.yml          5
release.yml             744
ci-publish.yml            0     <-- workflow_call only
ci-pipeline.yml           0     <-- workflow_call only
```

**A `workflow_call` workflow produces no run of its own.** Its jobs appear under
the caller's run, so `GET /actions/workflows/<file>/runs` returns
`total_count: 0` — not "healthy", not "never started", simply nothing, forever.
Implementing AC1 as written would have shipped a daily check that reports
`never ran` on `ci-publish.yml` on every execution: red for a reason that is not
a defect, which is worse than no check at all. It trains the reader to ignore the
one channel built to be believed.

It is also unnecessary, for the reason the parent ticket exists. **A reusable
workflow cannot `startup_failure` independently — it fails as its caller's
`startup_failure`.** That is literally `#1666`: `staging-deploy.yml` was refused
at run creation over what `ci-publish.yml`'s job requested. Watching the callers
is both necessary and sufficient, and watching the callee is impossible.

**Solution**: The watched set is derived from the tree rather than listed, and the
predicate is a **"no"**, not a "some": a workflow is watched when *no* path into
it is gated by a pull request, and it reaches the publisher or `deployment
promote` through an executable step.

The shape matters. "Has some trigger that isn't a pull request" also selects
`ci.yml`, which publishes transitively and runs on push — but `ci.yml` produces
the required `Validate` and `Detect Changes` contexts, so a `startup_failure`
there leaves the next pull request unmergeable within the hour. Its silence is
bounded by one PR rather than by ten weeks. The question is **does anything else
already report this**, never *does it touch delivery* — and the same sentence
correctly excludes `review-attestation.yml`, which is some evidence the cut is in
the right place.

Two smaller traps came out of the same work:

- **Reading a workflow as text matches prose.** A grep for `deployment promote`
  selected `pr-agent.yml`, where the string sits in a comment explaining the
  delivery model. Steps are read from the parsed document.
- **PyYAML folds the unquoted key `on` to the boolean `True`** (YAML 1.1). A
  plain `workflow.get("on")` returns nothing for every real file, every workflow
  then looks attended, and the watched set comes back empty — a monitor that
  passes by measuring nothing, which is the failure mode of the thing being
  fixed. `mypy` flagged the widened annotation this needs, and the annotation was
  widened rather than ignored, because the surprise is real.

And the monitor is in its own watched set by name. A checker blind to its own
`startup_failure` reproduces the defect one level up. It needs no special case to
work: when it runs, that execution *is* a run of it, reported `conclusion: null`
while in progress, which the classifier already treats as "not a verdict".

**Rule**: Before implementing a monitoring criterion, **ask the API whether the
thing it names can answer the question at all.** A specification is a claim about
the world, and this one named a file with no runs, in a repository where nobody
had ever needed to look. Correcting the criterion on the ticket, with the
measurement, cost one query; discovering it after merge would have cost a daily
red check that everyone learns to skip.

And when the criterion is "is this silent", the discriminator is never what the
workflow *does*. It is whether anything else already makes it loud.

**Tags**: `#github-actions` `#reusable-workflows` `#startup-failure` `#observability` `#specs` `#pr-1696`
