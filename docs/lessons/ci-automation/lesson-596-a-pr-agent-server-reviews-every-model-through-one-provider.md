---
id: lesson-596-a-pr-agent-server-reviews-every-model-through-one-provider
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, litellm, anthropic]
---

# A PR-Agent server reviews every model through one provider, so its fallback chain cannot mix NaN and Anthropic

**Context**: The forge reviewer (TOOL-080) reviewed with mimo and fell back to deepseek alone, while CI
draws from the whole reviewer pool, Haiku included. TOOL-117 (#2295) asks the forge to read the same
pool, so the plan was a chain of mimo, deepseek, glm and then Haiku as the last resort.

**Problem**: The chain cannot reach Anthropic. In `litellm_ai_handler.py` at v0.45.0, `OPENAI.API_BASE` sets
the handler's `self.api_base` once at start, and every completion passes it as `api_base`.
`LITELLM.CUSTOM_LLM_PROVIDER` is read from settings and added to every call. An `anthropic/claude-haiku-5-5`
fallback would therefore go to `api.nan.builders` as an OpenAI model, which is the failure of lesson-575
with no step env to override it: the server is one long-running process. Dropping both settings does not
help either. NaN needs forced streaming, and PR-Agent forces it only when the provider equals
`FORCE_STREAMING_CUSTOM_LLM_PROVIDER` and the api_base matches a substring, while
`STREAMING_REQUIRED_MODELS` is a constant, not a setting.

**Solution**: The forge chain holds the pool's NaN members only, heaviest first (mimo, deepseek, glm), and
`tests/test_pr_agent_config_render.py` derives that chain from `harness/reviewer-pool.json` and compares it
with the rendered ConfigMap. A pool change that adds, removes or reweighs a NaN member turns it red. An
Anthropic fallback for the forge needs a second route, filed with its options.

**Rule**: Before adding a model to a PR-Agent fallback chain, check which settings are per process. In
server mode, api_base and the LiteLLM provider are fixed when it starts, so one deployment serves one
provider. A second provider needs its own route, not a longer chain.

**Tags**: `#pr-agent` `#litellm` `#tool-117`
