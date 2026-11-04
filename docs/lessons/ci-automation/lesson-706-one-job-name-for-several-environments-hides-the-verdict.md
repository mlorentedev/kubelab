---
id: lesson-706-one-job-name-for-several-environments-hides-the-verdict
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github, deploy-merge]
---

# One job name for several environments hides which environment a run judged

**Context**: #3062 F11 decided that deploy-merge (DELIVERY-004, #1619) pauses every unattended merge while "the latest
completed deploy-verify run on master" is not green.

**Problem**: deploy-verify's `Argo CD status` job ran for both `argocd/kubelab-staging` and `argocd/kubelab-prod`
under that one name. Every merge to master gets both statuses within seconds, so a staging sync failure was a red run
followed ten seconds later by prod's green run. "The latest run" is whichever landed last, so the pause would almost
never hold for the staging failure it exists for. The run list carries nothing else that says which environment a run
was about.

A first design assumed the opposite problem. The workflow's header said every status in the repository starts a
skipped run on master, so the judge was written to step over "noise". Measured, all of the last 100 completed master
runs had a job that ran. The header was corrected in the same PR. The design had trusted a comment over a measurement,
and a pr-agent finding about page size was what prompted the measurement.

**Solution**: every deploy-verify job name now ends with the context it judged, `(argocd/kubelab-<env>)`.
`pause_reason` in `toolkit/features/deploy_merge.py` reads the newest run that holds a job for `staging` that ran, and
that job's conclusion decides. `tests/test_deploy_shape_widening.py` requires every deploy-verify job name to carry
its context, and the prefix to match the workflow's `startsWith`.

**Rule**: when something downstream keys on a workflow's runs, the job name is the only label the run list gives it.
A job that serves several environments or targets must name the one it ran for. Before designing around what a
comment says a run list contains, list it.

**Tags**: `#deploy-verify` `#deploy-merge` `#issue-3062`
