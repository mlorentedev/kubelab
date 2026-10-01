---
id: lesson-491-a-review-at-its-findings-cap-is-partial-by-construction
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, review]
---

# A PR-Agent review at its findings cap is partial by construction, and NaN cuts any unstreamed call at about 125 s

**Context**: The merge rule here requires a PR-Agent review whose `last_run.complete` is true. #1955 got reviews that published findings and still read `kind: partial`, and its other attempts published nothing (#1909). #1962 set out to fix both and was itself reviewed four times before the cause was measured.

**Problem**: Three facts, none visible from the PR or from `gh run view --log`:

- `allow_resolution` in PR-Agent 0.46.0's `pr_reviewer.py` marks a run complete only when it reports FEWER findings than `num_max_findings`, default 3. A review with three real findings is partial whatever its quality.
- NaN sits behind Cloudflare, which answers 524 to a request that sends no bytes for about 125 s, whatever `ai_timeout` says. A review prompt for a 30k-token diff takes mimo-v2.6-flash 275-300 s. #1962's own prompt, sent directly: 524 at 126 s unstreamed, 200 at 275 s streamed. Raising `ai_timeout` to 360 s changed nothing until requests were streamed.
- Upstream replays a failed call at two layers before the next model: the handler's `MODEL_RETRIES = 2` times the completion client's default retries. #1909's 720 s (run 36800846902) was mimo-v2.5 answering 401 at once, then deepseek timing out 2 x 3 x 120 s.

Two diagnoses were written into #1962 and retracted before these facts were read. Both came from arithmetic over durations, because `gh run view --log` drops every line after the step's huge "PR diff" artifact line: 336 lines against 356 in the raw archive, with every "Error during LLM inference" among the missing ones.

**Solution**: In `.pr_agent.toml`: `num_max_findings = 5`; `retry_same_model_on_timeout = false` and `num_retries = 0` (a timed-out call goes straight to the next model); `ai_timeout = 360`; and forced streaming. Streaming is enabled through `[litellm] custom_llm_provider`, `force_streaming_custom_llm_provider = "openai"` and `force_streaming_api_base_substrings = ["api.nan.builders"]`. Upstream needs all three. Each is repeated in the workflow env, which is read from the PR head, and in the forge reviewer's env, which reviews repositories without this toml. `tests/test_pr_agent_workflow.py` asserts each setting in both files, and that one `ai_timeout` per model fits inside the PR-Agent step's own `timeout-minutes: 13`. That step limit exists because a non-timeout `APIError` (a 5xx, a dropped stream) is still replayed once on the same model: `MODEL_RETRIES = 2` is a constant with no setting, so that worst case is 2 x 2 x 360 s. Cutting the step rather than the job leaves the next step time to name the failure. Proven before pushing with a local run of the pinned PR-Agent against #1962 (`CONFIG__PUBLISH_OUTPUT=false`): streaming mode, answer at about 300 s, no error.

**Rule**: Read a CI failure from the raw log archive (`gh api repos/<o>/<r>/actions/runs/<id>/logs`), never from `gh run view --log`, whenever a step logs a large artifact: the CLI silently drops what follows it. Before retrying a "partial" review, count its findings against `num_max_findings`. A model call that always dies near the same short duration may be a proxy in front of the provider, not the model or the client timeout. Reproduce it with one direct call before tuning anything.

**Tags**: `#pr-agent` `#1909` `#1955` `#1962`
