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
- A hung model is replayed at two layers before the fallback is consulted: the handler's retry (`MODEL_RETRIES = 2`, timeouts included while `retry_same_model_on_timeout` is true) times the completion client's default retries, which upstream's configuration.toml says "multiply" it. At `ai_timeout = 120` that is 2 x 3 x 120 s = 720 s on the primary alone. Run 36800846902 logs one "Generating prediction with openai/mimo-v2.5" and no fallback attempt in 728 s. The primary was `mimo-v2.5`, which NaN was retiring: review-sized calls hung, and minutes later a minimal call answered 401.
- The first version of this fix read the 720 s as 2 models x 3 attempts x 120 s, and turned off only the handler layer. That left 360 s on the primary. PR-Agent's own review of #1962 caught the contradiction.

**Solution**: `num_max_findings = 5`, `retry_same_model_on_timeout = false` and `num_retries = 0` in `.pr_agent.toml`, repeated as `PR_REVIEWER__NUM_MAX_FINDINGS`, `CONFIG__RETRY_SAME_MODEL_ON_TIMEOUT` and `CONFIG__NUM_RETRIES` in the workflow env (read from the PR head, so the fix reviews its own PR) and in the forge reviewer's env (it reviews repositories without this toml). Primary moved to `mimo-v2.6-flash`. `tests/test_pr_agent_workflow.py` asserts each setting in both files.

**Rule**: Before retrying a "partial" review, count its findings against `num_max_findings`. A failure that lasts the same number of seconds every time is a retry budget, not the model's speed. Find which model each attempt went to in the log before multiplying, because a product that fits the total can still assign the attempts to the wrong models.

**Tags**: `#pr-agent` `#1909` `#1955`
