---
tags: [spec, verification, templates]
created: "2026-08-07"
---

# Verification - ANSIBLE-033-dev-node-credentials

## Evidence

One row per acceptance criterion, each bound to the `features.json` feature that
carries its executable command. Fill `Evidence` with observed output and a date,
never with intent. `State` mirrors `features.json` and is **harness-owned**: an
agent may not promote a feature out of `pending`.

| AC | Feature | What it proves | State | Evidence |
| --- | --- | --- | --- | --- |
| AC1 | f1 | `gh` authenticated on ace2, working non-interactively | `pending` | |
| AC2 | f2 | Private clone → commit → push → PR from tmux, no agent forwarding | `pending` | |
| AC3 | f3 | Fine-grained token; `workflows: write` actually refused | `pending` | |
| AC4 | f4 | Role delivers the credential from SOPS; second pass `changed=0` | `pending` | |
| AC5 | f5 | No prod credential reachable from ace2 | `pending` | |
| AC6 | f6 | Token never in argv/logs/world-readable files; `gh` owns the sink | `pending` | |
| AC7 | f7 | Rotation runbook exists and is operational | `pending` | |

Two criteria are **not fully machine-checkable**, and are recorded here so the
gap is visible rather than assumed closed:

- **AC3** — a fine-grained PAT's **90-day expiry** and **All-repositories**
  scope are not exposed by the GitHub API. They are read off the token's
  settings page. `f3` verifies only the executable half (fine-grained prefix +
  workflow-write refusal); do not mark AC3 satisfied on that half alone.
  - Expiry observed: `<YYYY-MM-DD, expect 2026-11-05>`
  - Repository access observed: `<All repositories / narrowed>`
  - Permissions observed: `<contents:w, pull-requests:w, checks:r, statuses:r, metadata:r>`
- **AC4** — the aggregate `changed=0 failed=0` is necessary but not sufficient.
  Read the **per-task list** of the second pass; a task that flips to `changed`
  while the total stays 0 is the failure mode ANSIBLE-028 hit.
  - Pass 1: `<ok=N changed=N failed=N>`
  - Pass 2: `<ok=N changed=N failed=N>` — tasks reporting changed: `<none / list>`

## Test status

- Test suite: `make test` -> `<output>`
- Probe scripts: `bash -n` + `shellcheck` on `probes/*.sh` -> `<output>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-033-dev-node-credentials/` -> `specs/archive/ANSIBLE-033-dev-node-credentials/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
- [ ] Token rotation (2026-11-05) tracked outside this spec — the spec archives, the expiry does not
