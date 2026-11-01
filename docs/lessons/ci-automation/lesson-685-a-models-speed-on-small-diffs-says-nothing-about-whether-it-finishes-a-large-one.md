---
id: lesson-685-a-models-speed-on-small-diffs-says-nothing-about-whether-it-finishes-a-large-one
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, nan, llm, reviewer]
---

# A model's speed on small diffs says nothing about whether it finishes a large one

**Context**: The forge reviewer (PR-Agent 0.45.0 on prod) tries its models in `forge_rank` order. On 2026-10-18 deepseek-v4-flash went first because it was fastest, and the output cap went to 65536 tokens after deepseek stopped at NaN's default of 32768 (lesson-601).

**Problem**: From 2026-10-29 to 2026-11-01, 3 of 7 forge reviews lost about 9 minutes before publishing. In Loki each one shows the same sequence. First `Generating prediction with openai/deepseek-v4-flash`. About 5 minutes later, `Streaming response resulted in empty content but completed with finish_reason: length`, which 0.45.0 then hides behind `APIError.__init__() missing 'request'`. A second attempt fails the same way, then glm5.3-flash publishes 5 to 9 minutes later. All three were large diffs. On the four small diffs deepseek answered in 7 s to 4 min. So deepseek's reasoning chain grows with the diff, and on a large one it spends the whole 65536-token cap before it writes an answer. Raising the cap does not help, because a stream still reasoning at about 600 s is cut anyway. A gunicorn `SIGKILL! Perhaps out of memory?` in the same window was not memory: the VPS kernel log had no OOM, and gunicorn prints that line for any worker SIGKILL.

**Solution**: glm moves to `forge_rank` 1 and deepseek to 2 (owner, 2026-11-01). glm is slower on a small diff, but it finished every large one deepseek dropped. A large review now costs one glm run, not two deepseek failures followed by glm. The test that pins the first model states the measured reason. Giving glm a `low` reasoning effort needs PR-Agent 0.47.0 (#2905).

**Rule**: Order a fallback chain by how often each model finishes the work, not by its median latency. A fast model that fails on the hard inputs costs its failure time and the fallback's full time on exactly the requests that were already slow. Read the `finish_reason` in the logs before replaying anything: the server had already recorded the answer.

**Tags**: `#pr-agent` `#nan` `#reviewer` `#issue-2905`
