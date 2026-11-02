---
tags: [spec, verification, templates]
created: "2026-11-01"
---

# Verification - AI-025

## Evidence

- [x] AC1 (speed measured, no change) -> lesson-690; from ace2 every NaN chat model answers a short prompt in 0.8-1.2 s median, as one chunk, and title, tag and follow-up generation run after the answer.
- [x] AC2 (SearXNG, no port, memory-bounded, Open WebUI searches through it) -> commit `f4f0f445` (#2930) / `tests/test_open_webui_web_search.py`; live on ace2, 95 MiB in use (lesson-690's 128 MiB was a local Colima run before deploy, a different host), 33 results from inside the open-webui container, and the operator's chat question returned cited web results (2026-11-01).
- [x] AC3 (Pyodide runs Python from a chat) -> #2947 / `test_every_chat_starts_with_the_code_interpreter_on`, `test_code_runs_in_the_browser_not_on_ace2`; the operator's chat returned the first 20 primes and their sum (2026-11-01).
- [x] AC4 (memory carries a fact to a new chat) -> #2947 / `test_memories_are_saved_without_being_asked`; a fact told in one chat was recalled in a new chat (operator, 2026-11-01). That chat asked the model to remember, so it proves the memory path, not the background review. The review is on because the env is what the instance reads: `ENABLE_PERSISTENT_CONFIG=false` (`tests/test_agent_stack_role.py`), and with it v0.12.5's `Config.get()` returns the env value and `seed_defaults()` writes no row (`backend/open_webui/models/config.py:144-150, 249-266`).
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

## Review dispositions

First review (nan/deepseek-v4-flash, 690bd91c, FAIL):

- **Blocker, AC4 env inert on a booted instance**: declined. The premise is that persistent config is on. The role sets `ENABLE_PERSISTENT_CONFIG=false`, a test asserts it, and in v0.12.5 that makes `Config.get()` return the env value for every key (`models/config.py:144-150`). The evidence is now recorded under AC4.
- **Major, tests compare the template with itself**: accepted as a limit and not changed here. The link from template to running instance is the persistent-config guard above. A live check per AC would need the admin token on the node; the SearXNG part is #2970.
- **Major, no SearXNG probe**: ticketed as #2970 (AI-026). Adding it needs a provision of ace2 to prove, which is outside this change.
- **Minor, web results can become persisted memories**: ticketed as #2971 (SEC-041), an operator decision.
- **Minor, magic bound in the memory test**: applied. The bound is now `< 10` with its reason: more often than v0.12.5's default, which is why the key is set.
- **Minor, lesson-687 missing from the promotion list**: applied.
- **Minor, 95 vs 128 MiB**: explained under AC2 (two hosts).
- **Minor, features.json entries still pending**: not changed. Only the harness may set `passing`.

Second review (nan/qwen3.8-flash, 931dcf5d, PASS WITH GAPS):

- **Major, `searxng.container_port` wired on the client side only**: ticketed on #2970. The fix needs a provision of ace2 to prove which variable the image's server reads.
- **Major, no read of the instance's effective config**: ticketed on #2970, as a post-deploy check of `configs/export`.
- **Major, no SearXNG probe**: #2970 (carried).
- **Minor, web results can become memories**: #2971 (carried).
- **Minor, features.json pending**: not changed. Only the harness may set `passing`.
- **Minor, searxng.env change has no restart path**: accepted. The key is generated once on the node and never rotated in-band.
- **Minor, #2947 had no triage comment yet**: it gets one before merge.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/containers-docker/lesson-690-measure-the-model-before-tuning-open-webuis-background-calls.md
- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/containers-docker/lesson-692-open-webuis-pyodide-runs-get-60-seconds-including-the-package-download.md
- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/containers-docker/lesson-687-an-open-webui-feature-toggle-decides-which-tools-the-model-gets.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: configuration inside the agent_stack role, and ADR-068 already places the agent tooling on ace2.
- [x] New pattern candidate for `00_meta/patterns/`? no: specific to Open WebUI on one node.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/AI-025/` -> `specs/archive/AI-025/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
