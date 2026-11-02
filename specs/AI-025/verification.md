---
tags: [spec, verification, templates]
created: "2026-11-01"
---

# Verification - AI-025

## Evidence

- [x] AC1 (speed measured, no change) -> lesson-690; from ace2 every NaN chat model answers a short prompt in 0.8-1.2 s median, as one chunk, and title, tag and follow-up generation run after the answer.
- [x] AC2 (SearXNG, no port, memory-bounded, Open WebUI searches through it) -> commit `f4f0f445` (#2930) / `tests/test_open_webui_web_search.py`; live on ace2, 95 MiB, 33 results from inside the open-webui container, and the operator's chat question returned cited web results (2026-11-01).
- [x] AC3 (Pyodide runs Python from a chat) -> #2947 / `test_every_chat_starts_with_the_code_interpreter_on`, `test_code_runs_in_the_browser_not_on_ace2`; the operator's chat returned the first 20 primes and their sum (2026-11-01).
- [x] AC4 (memory carries a fact to a new chat) -> #2947 / `test_memories_are_saved_without_being_asked`; a fact told in one chat was recalled in a new chat (operator, 2026-11-01).
- [x] AC5 (new chat starts with image, web search and code interpreter on) -> #2904 (image), `f4f0f445` (web search), #2947 (code interpreter) / `test_every_chat_starts_with_the_image_tool_on`, `test_every_chat_starts_with_web_search_on`, `test_every_chat_starts_with_the_code_interpreter_on`.
- [x] AC6 (role env and templates hold it, tests cover it, rerun `changed=0`) -> `tests/test_agent_stack_role.py`, `tests/test_image_pull_budget.py`; ace2 provisioned from each branch, reruns `ok=217 changed=0`.

## Test status

- Test suite: every `features.json` verification command passes (6, 2, 1, 3 and 74 tests).
- Manual smoke test: on ace2 the operator ran a web-search question, Python in a chat, and a memory carried across chats; all three worked (2026-11-01).
- No regressions in existing test suite: yes; CI green on #2930 at merge.

## Decisions made during implementation

- Speed was measured before tuning: the background calls run after the answer, so no task-model change was made (lesson-690).
- One search engine (SearXNG) instead of several, because v0.12.5 takes one engine and SearXNG aggregates others itself.
- Code runs in the browser (Pyodide), never on ace2. Its 60 s limit is hardcoded and includes the package download, so a first matplotlib import can time out over a slow link (lesson-692).

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/containers-docker/lesson-690-measure-the-model-before-tuning-open-webuis-background-calls.md
- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/containers-docker/lesson-692-open-webuis-pyodide-runs-get-60-seconds-including-the-package-download.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: configuration inside the agent_stack role, and ADR-068 already places the agent tooling on ace2.
- [x] New pattern candidate for `00_meta/patterns/`? no: specific to Open WebUI on one node.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AI-025/` -> `specs/archive/AI-025/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
