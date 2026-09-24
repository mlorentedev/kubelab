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
- [ ] AC7, by effect: **pending.** It needs the three OAuth values in SOPS (operator) and resume's
  `publish-drive` preflight (resume#272). This PR does not close #1626 for that reason.

## Test status

- `pytest tests/test_gitea_actions_secrets.py`: 32 passed.
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
- **Placeholder values count as missing.** A `CHANGEME` would pass the workflow's empty-input
  guard and then fail at the provider's API, which does not say which input was wrong.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? No. The silent-empty-secret shape is already the ticket's content, and the incident behind it is resume's (its L-042).
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No. It follows the existing delivery pattern (`sync_to_secret_manager`); no new decision class.
- [ ] New pattern candidate for `00_meta/patterns/`? No. It is kubelab-specific tooling.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-062-gitea-actions-secrets/` -> `specs/archive/TOOL-062-gitea-actions-secrets/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
