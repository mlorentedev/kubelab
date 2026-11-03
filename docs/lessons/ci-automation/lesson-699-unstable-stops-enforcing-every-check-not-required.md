---
id: lesson-699-unstable-stops-enforcing-every-check-not-required
type: lesson
status: active
created: "2026-11-03"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github, merge]
---

# Accepting `mergeable_state: unstable` stops enforcing every check that is not required

**Context**: deploy-merge (DELIVERY-004, #1619) merged only `clean` PRs. #2883 waited 6.5h because `add-to-project`
hit a rate limit and made the PR `unstable`. #2910 widened the accepted states to `clean` and `unstable`, on the
reasoning that the judge checks every required context itself.

**Problem**: `unstable` does not mean "a harmless check failed". It means some context that branch protection does
not require is not passing, and it does not say which one. On this repository that set includes `Drift / staging` and
`Drift / prod` (the only generator-equals-values check, ADR-027), GitGuardian, `Spec archive gate` and `hygiene`. So
accepting the state switched all of them off for the merging actor, not just `add-to-project`. The adversarial review
found it (Major, #2983). The motivating case was benign, so it had not been noticed.

**Solution**: the judge now reads every reported context, not only the required ones, and refuses any that is not
passing (still running included) unless it is named in `ALLOWED_UNSTABLE = frozenset({"add-to-project"})` in
`toolkit/features/deploy_merge.py`. `tests/test_deploy_shape_widening.py` pins that set. `make mutate` adding
`Drift / staging` to it goes red.

**Rule**: a state that summarises other checks ("unstable", "some checks failed") is an allow-list nobody wrote down.
Before accepting it, name the contexts it may stand for and refuse every other one.

**Tags**: `#deploy-merge` `#branch-protection` `#pr-2910` `#issue-2983`
