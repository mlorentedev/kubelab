---
id: lesson-634-a-check-run-posted-with-github-token-joins-another-workflows-suite
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github, branch-protection, check-runs]
---

# A check-run posted with `GITHUB_TOKEN` joins another workflow's suite, and protection loses it when that workflow re-runs

**Context**: `deploy-shape` (DELIVERY-004) is a required context on master. Its
workflow judged the PR and published the verdict with
`POST /repos/{repo}/check-runs` (`success`, `neutral` or `failure`), because a
commit status has no neutral.

**Problem**: three PRs stayed `BLOCKED` with every required check green, and
`gh pr checks --required` showed `deploy-shape` as `skipping` (neutral). The
merge box said otherwise: `deploy-shape`, "Expected, waiting for status to be
reported". GitHub had not attached the check-run to the deploy-shape workflow's
own suite. It went to the first github-actions suite on the head sha, which
belongs to whichever workflow started first:

| PR | suite that held the check-run | that workflow ran again on the sha | counted |
|---|---|---|---|
| #2705 | Config Drift Gate | no | yes |
| #2708 | Repo hygiene | no | yes |
| #2707 | review-attestation | yes | no |
| #2709 | review-attestation | yes | no |
| #2710 | Spec Gate | yes | no |

review-attestation and Spec Gate run again on the same sha by design. Once a
newer suite of the workflow exists, branch protection no longer sees the older
suite's check-runs. A re-run of the deploy-shape workflow did not help on
#2709: the new check-run went into the same superseded suite. Neither did
re-running the superseded suite itself. Whether a PR could merge depended on
which workflow GitHub happened to start first, so the gate passed on some PRs
and silently refused others.

**Solution**: publish the verdict as a commit status, which belongs to no suite.
It is `success` for both evaluated outcomes, with the verdict in the description,
and `failure` when the verdict is unknown. The neutral answer only ever served
the reader: the status grants nothing, since every consumer recomputes the
verdict. `tests/test_deploy_shape.py` fails if the workflow posts to anything
but `statuses` or keeps `checks: write` (DELIVERY-011, #2714).

**Rule**: a required context produced by a workflow is either the job's own
check-run, which lives in that workflow's suite, or a commit status. Never use a
check-run created through the API with `GITHUB_TOKEN`. Its suite is not yours to
choose. When a PR is `BLOCKED` with every required check green, read the merge
box (or ask someone to) before reading more API fields: it names the context it
is still waiting for, and the API does not.

**Tags**: `#branch-protection` `#check-runs` `#delivery-011` `#issue-2714`
