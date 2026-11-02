---
id: lesson-688-measure-the-model-before-tuning-open-webuis-background-calls
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, open-webui, nan, searxng, performance]
---

# Measure the model before tuning Open WebUI's background calls

**Context**: AI-025 (#2915) set out to make Open WebUI on ace2 feel like a hosted
assistant. The first PR planned to speed up answers by moving title, tag and
follow-up generation to a small task model, which is the usual advice.

**Problem**: That advice assumes the background calls compete with the answer.
In v0.12.5 they do not. `background_tasks_handler` (`utils/middleware.py:3539`)
runs after the answer is complete, and autocomplete is off by default
(`ENABLE_AUTOCOMPLETE_GENERATION`). A task-model change would have shipped,
passed its tests, and changed nothing the operator could see.

The measurement from inside the container settled it. A streamed request to each
NaN chat model, timed to its first token, with the key read from the container's
env and never printed, showed two things:

- Every model answered a short prompt in 0.8-1.2 s median.
- Every answer arrived as one chunk. NaN does not stream, so a long answer shows
  nothing until it is complete, whatever Open WebUI does.

A first run with `max_tokens: 200` reported no tokens at all for two models: they
spent the budget on `reasoning_content` and never reached `content`. A timing
script has to count reasoning deltas, or it reads a thinking model as silent.

**Solution**: No task-model or default-model change was made. The PR became web
search (SearXNG), the largest functional gap. SearXNG answers Open WebUI's
`format=json` request with 403 unless `search.formats` lists `json`, and it ran
with `cap_drop: ALL` and a read-only settings mount (measured locally: up,
128 MiB, results from Brave and Google, DuckDuckGo answering with a CAPTCHA).

**Rule**: Before tuning what runs around a request, find out whether it runs
before, during or after it. Then time the request itself at the source, counting
every kind of token the backend emits.

**Tags**: `#open-webui` `#nan` `#searxng` `#performance` `#ai-025`
