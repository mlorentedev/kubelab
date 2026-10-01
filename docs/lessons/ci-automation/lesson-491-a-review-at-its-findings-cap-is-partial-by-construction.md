---
id: lesson-491-a-review-at-its-findings-cap-is-partial-by-construction
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, review]
---

# A PR-Agent review at its findings cap is partial by construction, and a timeout is retried on the model that just hung

**Context**: The merge rule here requires a PR-Agent review whose `last_run.complete` is true. #1955 got three reviews in a row that published findings and still read `kind: partial`, and its other attempts published nothing after exactly 720 s (#1909).

**Problem**: Two upstream defaults, neither visible from the PR:

- `allow_resolution` in PR-Agent 0.46.0's `pr_reviewer.py` marks a run complete only when it reports FEWER findings than `num_max_findings`, whose default is 3. A review with three real findings is therefore partial whatever its quality, because at the cap there may be more it did not say. Read as a failed run, it sends you retrying a review that worked.
- `retry_same_model_on_timeout` defaults to true, with three attempts per model at `ai_timeout = 120`. A model that hangs on a large diff hangs again, so two models cost 2 x 3 x 120 s = 720 s before "Failed to review PR". The same 720 s +/- 9 s on five runs was the tell. NaN retiring the primary (`mimo-v2.5` now answers 401) left only the model that hangs.

**Solution**: `num_max_findings = 5` and `retry_same_model_on_timeout = false` in `.pr_agent.toml`, repeated as `PR_REVIEWER__NUM_MAX_FINDINGS` and `CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT` in the workflow env (read from the PR head, so the fix reviews its own PR) and in the forge reviewer's env (it reviews repositories without this toml). Primary moved to `mimo-v2.6-flash`. `tests/test_pr_agent_workflow.py` asserts both settings in both files.

**Rule**: Before retrying a "partial" review, count its findings against `num_max_findings`. A failure that lasts the same number of seconds every time is a retry budget, not the model's speed: multiply the timeouts out before tuning anything else.

**Tags**: `#pr-agent` `#1909` `#1955`
