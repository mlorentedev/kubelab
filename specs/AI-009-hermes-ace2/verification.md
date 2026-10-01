---
tags: [spec, verification, templates]
created: "2026-09-30"
---

# Verification - AI-009-hermes-ace2

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Live measurements

### PR 1 (`feat/ai009-agent-stack`), staging ace2, 2026-10-01

- **Unconfigured path** (no OIDC secret in prod SOPS): `make provision NODE=ace2 ENV=staging TAGS=agent_stack` twice: `changed=2` (directory, session key), then `changed=0`. Open WebUI not started; the play names the missing key.
- **Configured path**, with `EXTRA='agent_stack_webui_oidc_client_secret=<placeholder>'` so the deploy block runs before the real client exists (OIDC cannot succeed with it and the login form is off, so no account can be created). First pass `changed=7`, health check green after ~6 retries; second pass `changed=0`.
- **AC4 bind**: `http://100.64.0.5:3080/health` → 200; `http://172.16.1.5:3080/health` → no listener.
- **AC8**: Glances container API, 3 min after start, idle: cgroup usage 1489 MiB, of which 591 MiB is reclaimable page cache, so a working set of 897 MiB against the 1536 MiB limit. Node available memory 10073 of 11739 MiB. Open WebUI loads its local embedding model at start; PR 5's `RAG_EMBEDDING_ENGINE=openai` should lower this, and AC8 is re-measured then.
- **Teardown**: provision again without the placeholder: the container is taken down and `compose-webui.yml` and `webui.env` are removed (`changed=3`); next pass `changed=0`; port 3080 has no listener.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AI-009-hermes-ace2/` -> `specs/archive/AI-009-hermes-ace2/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
