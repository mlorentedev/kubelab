---
id: "AI-025"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-11-01"
issue: "mlorentedev/kubelab#2915"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "operator requested 2026-11-01, live session (13 active, limit 10, 2026-11-01)"
---

# AI-025 Open WebUI as a daily assistant

## Why

The operator wants Open WebUI on ace2 (#1933) to replace hosted assistants such as ChatGPT, Gemini and Claude for day-to-day use. As of 2026-11-01 it answers fast and generates images, but it cannot search the web. Its code interpreter and memory exist in v0.12.5, but no chat starts with them on, and nothing saves memories unless asked.

## What

- **Web search.** SearXNG runs beside Open WebUI on ace2, on that project's network with no published port. Open WebUI searches through it.
- **Default tools.** Every new chat starts with image generation, web search and the Pyodide code interpreter on.
- **Memory.** Memory background review is on, so facts from one chat reach the next without being asked for.
- **Speed.** Measured, not changed: from ace2, each NaN chat model returns a short answer in 0.8-1.2 s. Title, tags and follow-ups run after the answer (#2915 AC1).

## Out of scope

- **The slow first page load.** That is client link latency (#2482 comment, 2026-11-01).
- **Streaming.** NaN sends each answer as one chunk, which Open WebUI cannot change.
- **A server-side code interpreter (Jupyter).** The operator chose Pyodide in the browser.
- **Paid search APIs and multi-engine fallback.** v0.12.5 takes one engine.

## Risks / open questions

- **SearXNG hardening.** It runs with `cap_drop: ALL` and a read-only settings mount. Whether the image starts that way is measured on ace2 before merge.
- **Search load on the upstream engines.** They may rate-limit SearXNG's single IP. Results then degrade to the engines that still answer.
- **Background review cost.** It calls the task model every N turns and spends NaN quota.

## Acceptance criteria

The acceptance criteria are #2915 AC1-AC6.

- [x] AC1: speed measured. No change.
- [ ] AC2: SearXNG answers Open WebUI's web search, with no port, memory-bounded.
- [ ] AC3: Pyodide runs Python from a chat.
- [ ] AC4: memory carries a fact to a new chat.
- [ ] AC5: a new chat starts with image, web search and code interpreter on.
- [ ] AC6: the role's env and templates hold all of it, tests cover it, and the rerun gives `changed=0`.

## References

- Parent spec: AI-009 (#1933). Image default: #2904.
- Open WebUI v0.12.5: `routers/retrieval.py:2232` (one engine), `utils/tools.py` (builtin tools by feature), `retrieval/web/utils.py` (non-global addresses refused).
