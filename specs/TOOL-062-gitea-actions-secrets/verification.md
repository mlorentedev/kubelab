---
tags: [spec, verification, templates]
created: "2026-09-23"
---

# Verification - TOOL-062-gitea-actions-secrets

## Evidence

All tests are in `tests/test_gitea_actions_secrets.py`.

- [x] AC1: a plan-only run lists the creations and writes nothing.
  `test_plan_only_writes_nothing_and_never_prints_a_value` checks four `(create, from` lines and no PUT.
  Live against prod on 2026-09-24: the command read the forge and exited 1 with four `NO VALUE`
  lines, because the operator has not landed the values yet.
- [x] AC2: `--apply` creates, and a re-run changes nothing.
  `test_apply_writes_all_four_and_a_second_run_has_nothing_to_do`.
- [x] AC3: `--force` re-pushes what already exists.
  `test_force_re_pushes_what_the_forge_already_has` and
  `TestThePlan::test_force_rewrites_every_valued_declared_secret_and_nothing_else`.
- [x] AC4: a missing SOPS value is never written, and the run exits non-zero naming it.
  `test_a_missing_value_is_named_never_written_and_fails_the_run`,
  `test_plan_only_also_fails_when_a_value_is_missing`, `test_a_placeholder_is_not_a_value` and
  `test_execute_never_writes_a_missing_value`.
- [x] AC5: an undeclared live secret is reported and never removed.
  `TestThePlan::test_an_undeclared_live_secret_is_reported_and_never_removed` also asserts the plan
  has no field named like a deletion.
- [x] AC6: no value appears in the plan, the output or any repr.
  `test_the_plan_holds_no_values_by_construction`,
  `test_a_failed_write_is_recorded_per_secret_and_the_rest_still_run` (report repr),
  `test_the_value_travels_in_the_body_only`, and the `VALUE not in result.output` checks in every
  CLI test.
- [x] AC7, by effect: resume's `publish-drive` run 96 (dispatched 2026-09-30) reports all 4 inputs
  configured in its preflight, and each of the three uploads returns HTTP 200. The Drive folder lists
  `cv-manuel-lorente-alman-{altacv,ats,awesome}-2026-09-30.pdf`, created at 03:21 UTC. Recorded in
  #1936, after the operator restored the three OAuth values and ran `actions-secrets --apply`.

## Test status

- `pytest tests/test_gitea_actions_secrets.py`: 35 passed after the review fixes (32 before); 40 after #2166 (2026-10-10), which added the five escaped-echo cases.
- Secrets and Gitea subset (`-k "secret or gitea or catalog or expiry"`): 554 passed.
- Full suite: `pytest -q --no-cov`: 2587 passed, 15 skipped, 155 deselected (4m10s).
- `ruff check`, `ruff format --check` and `mypy` on the four changed modules and the test file: clean.
- Live read on 2026-09-23: superadmin basic auth
  `GET /repos/personal/resume/actions/secrets` returned `[]` (200).
- Live plan-only run against prod: exit 1, four `NO VALUE` lines. That is the expected state
  until the values are landed.

## Decisions made during implementation

- **The catalog, not `common.yaml`, holds the declaration.** The ticket body proposed a list in
  `common.yaml`. I followed the `sync_to_secret_manager` precedent instead: a second list would
  declare a fact the catalog entry already owns.
- **The secret name is derived from the key path's leaf.** It is validated against Gitea's naming
  rule, and a catalog test asserts that no two entries deliver the same name to one repository.
- **The planner receives the set of valued key paths, never the values.** So a plan cannot carry
  a credential at all; it is not merely filtered out of the output.
- **An incomplete declaration exits 1 in plan mode too.** "Nothing to write" because a source is
  missing is not convergence.
- **Review of #1816, all applied:**
  - `features.json` states went back to `pending`: only the harness may write `passing`.
  - The write-time empty-value refusal now has a test.
  - One repository failing to list becomes `unreachable` instead of aborting the run.
  - A forge error that echoes the value is redacted before it is recorded.
- **Placeholder values count as missing.** A `CHANGEME` would pass the workflow's empty-input
  guard and then fail at the provider's API, which does not say which input was wrong.

## Adversarial review findings

`review-round1.md` (2026-10-10, FAIL on one Blocker). Each finding's disposition:

| # | Finding | Disposition |
|---|---|---|
| 1 | Blocker: a forge error carrying the value JSON-escaped passes `str.replace(value, ...)` and prints it | Fixed in #2166: `_redact` replaces the verbatim, JSON, Go-JSON (`\u0026`) and repr forms; `test_a_forge_error_that_echoes_an_escaped_value_is_redacted` runs all five, and `make mutate` went red with only the verbatim form. |
| 2 | Major: live secrets are listed only on repositories the catalog names, so an undeclared secret on any other repository is never reported (AC5) | Declined for this spec, ticketed as #2165 (TOOL-105). The proposal scopes the comparison per declared repository ("For each repository the plan compares three things: the declared names, the live names..."), and AC1 is written for `personal/resume`. The gap is real at forge scale and needs its own enumeration and report shape, which #2165 states. The test the review cites passes `targets=()` with a live repository, a state the CLI cannot produce; it pins the planner, not the CLI's reach. |
| 3 | Minor: the redaction test asserted against `repr(report)`, which escapes the string again | Fixed in #2166: the assertion reads the recorded message itself. |

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/toolkit-tooling/lesson-545-a-fake-that-answers-nothing-cannot-test-what-the-code-prints-of-the-answer.md (the escaped-echo recurrence from finding 1, amended in #2166). The silent-empty-secret shape itself is the ticket's content, and its incident is resume's (its L-042).
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: It follows the existing delivery pattern (`sync_to_secret_manager`); no new decision class.
- [x] New pattern candidate for `00_meta/patterns/`? no: It is kubelab-specific tooling.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-062-gitea-actions-secrets/` -> `specs/archive/TOOL-062-gitea-actions-secrets/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
