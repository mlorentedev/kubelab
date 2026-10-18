---
id: lesson-597-a-reviewer-that-sends-no-max-tokens-inherits-the-providers-completion-cap-and-loses-the-review-to-its-own-reasoning
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, nan, forge]
---

# A reviewer that sends no max_tokens inherits the provider's completion cap, and loses the review to its own reasoning

**Context**: The forge reviewer (`deploy/pr-agent`, TOOL-080) failed on personal/resume #559 and #576 on
2026-10-18 with `Streaming response resulted in empty content but completed with finish_reason: length`
on both `mimo-v2.6-flash` and `deepseek-v4-flash`, then `APIError.__init__() missing 1 required
positional argument: 'request'`. Nothing was published (TOOL-093, #1957). The same signature closed
TOOL-096 (#1966) on the GitHub path without a measured cause.

**Problem**: Two things looked like the cause and were not. The `APIError` line looks like the crash, but
it is cosmetic: 0.45.0 raises `openai.APIError(msg)` without the `request` argument its constructor
requires (`litellm_helpers.py`, fixed in 0.47.0), the `TypeError` is re-wrapped as an `APIError`, and the
replay and the fallback still run. And `finish_reason: length` is not one failure but two, which a replay of
one logged review prompt (9.6k tokens in) separated:

- **deepseek-v4-flash hits a token cap.** With no `max_tokens` it stopped at exactly 32768 completion
  tokens, `length`; with `max_tokens=100000` it finished at 41445. PR-Agent's `max_output_tokens`
  defaults to 0, so it sends none. Its reviews on the pod reasoned for up to 28k tokens, so the tail sat
  against the cap.
- **mimo-v2.6-flash hits a clock.** It has no such cap (72918 tokens, no `max_tokens`, `stop`). A run at
  `reasoning_effort=low` ended `length` at 607 s with 22462 tokens, all reasoning, while an unconstrained
  run of the same prompt finished at 396 s. Most failures on the pod sit at 605 to 608 s. Effort `low`
  changed nothing, as #1966 found, and a larger `max_tokens` cannot move a time limit.

**Solution**: `CONFIG__MAX_OUTPUT_TOKENS=65536` in `pr-agent.env` for the deepseek half. Against the pinned
0.45.0 image and a stub that answers `length` once, the request body carries `max_tokens: 65536` with the
setting and `null` without it. `test_the_output_cap_is_above_the_providers_default` fails on the old file
(cap 0) and passes on the new one. The mimo half has no config fix on 0.45.0: PR-Agent retries a model
twice before the fallback (`MODEL_RETRIES`, a constant), so a mimo cut costs 20 minutes before deepseek
runs. What would help is a faster first model, or glm5.3-flash at `reasoning_effort=low` (24 s, 1940
reasoning tokens on the same prompt), which needs `additional_reasoning_effort_models` and so an image
newer than 0.45.0.

**Rule**: When a reasoning model's stream ends `finish_reason: length` with no content, read the totals at
the cut before choosing a lever. A round power of two (32768) is a token cap, and a client `max_tokens`
moves it. The same cut at an unremarkable token count and a constant elapsed time is a clock, and only a
different model or less reasoning moves it. A client that talks to a reasoning model through a gateway
states its completion budget, because the default is the gateway's and it counts reasoning.

**Tags**: `#pr-agent` `#nan` `#tool-093`
