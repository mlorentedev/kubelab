---
id: lesson-602-a-spending-weight-is-not-an-order-so-a-chain-derived-from-it-put-the-slowest-model-first
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, reviewer-pool, forge]
---

# A spending weight is not an order, so a chain derived from it put the slowest model first

**Context**: #2468 made the forge reviewer's model chain follow `harness/reviewer-pool.json` instead of a hand-written list: the NaN members that carry a `pr_agent.weight`, heaviest first. TOOL-093 (#1957) was then traced to the first model of that chain.

**Problem**: `weight` is CI's spending share (a draw: mimo 27, deepseek 19, glm 19, Haiku 35). Read as an order it put mimo-v2.6-flash first on the forge, where a server cannot draw and tries its models in turn. Replaying one logged review prompt with `max_tokens=65536` took 116 s on deepseek, 210 s on glm and 488 s on mimo, and a stream still reasoning at about 600 s is cut (lesson-601). The test that held the chain to the pool passed throughout, because it derived the expected chain from the same weights: it proved the env and the pool agreed, not that the order was a good one.

**Solution**: A separate key, `pr_agent.forge_rank` (deepseek 1, glm 2, mimo 3), in kubelab's copy of the pool only; the chain test sorts by it, the file's `$comment` declares it as a divergence from dotfiles' copy, and `tests/test_reviewer_pool.py` pins that it numbers exactly the NaN chain and that no CI weight moved. The consumers of the file ignore keys they do not read (dotf decodes it with a plain `json.Unmarshal`, `scripts/pr-agent-route.sh` selects fields with `jq`), so the extra key changes nothing in the CI draw.

**Rule**: A number that means "how often" does not also mean "in what order". When a config is derived from a source file, ask what each field of the source is for before reusing one as a sort key, and give a second purpose its own field. A test that derives its expectation from the same field the code reads cannot catch a wrong choice of field, so pin the property you wanted (here: the fast model is first) next to the derivation.

**Tags**: `#pr-agent` `#reviewer-pool` `#tool-093`
