---
id: lesson-575-a-pr-agent-toml-provider-applies-to-every-model
type: lesson
status: active
created: "2026-10-15"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, litellm, anthropic]
---

# A PR-Agent toml provider applies to every model, so a second provider has to override it

**Context**: TOOL-082 (#1843) added Anthropic models next to NaN in the PR-Agent review job. NaN is an
OpenAI-compatible endpoint, so `.pr_agent.toml` declares `[litellm] custom_llm_provider = "openai"`.
The Anthropic attempts set their own model and key in the step's env.

**Problem**: The first live Sonnet run (38683281099, #2302) failed before any request reached Anthropic:
`openai does not support parameters: ['thinking']`. The provider setting is not scoped to the models
that need it. LiteLLM sends every model through the transport the toml names, so it sent
`anthropic/claude-sonnet-5-5` through the OpenAI one and rejected the extended-thinking parameter that
PR-Agent adds for Claude. Unit tests could not catch it: they read the workflow, not LiteLLM's routing.
The `anthropic/` prefix on the model name did not override it.

**Solution**: Both Anthropic steps set `LITELLM__CUSTOM_LLM_PROVIDER: anthropic` beside `ANTHROPIC__KEY`
(55f12ad3). The env layer overrides the toml for that step only, and the NaN step keeps the toml's
value. The next Sonnet run (38685369694) published at 116,858 tokens in, 19.1 s.
`test_every_request_to_nan_is_streamed` now requires the override on every Anthropic attempt, and it
goes red without it.

**Rule**: A setting in `.pr_agent.toml` is global to the run. When a step reviews on a provider other than
the one the toml was written for, every provider-scoped key, `custom_llm_provider` first, needs an
explicit override in that step's env, and a test that names it. Prove a new provider with one live run
before trusting the unit tests: a refused request is the only measurement of transport routing.

**Tags**: `#pr-agent` `#litellm` `#pr-2302`
