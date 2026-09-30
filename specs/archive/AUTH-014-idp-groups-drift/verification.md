---
tags: [spec, verification, templates]
created: "2026-09-29"
---

# Verification - AUTH-014-idp-groups-drift

## Evidence

- [x] AC1 (drift or ok per user) -> `668d4915`, `test_idp_groups_drift_when_the_live_users_database_lags` (other groups, declared user missing, live user undeclared) and `test_idp_groups_that_match_are_ok_whatever_their_order`. Live negative, 2026-09-29: with `operator` declared `admins,users` in a local-only edit (restored, not committed), `make auth-review ENV=staging` gave `authelia operator declared=admins,users live=users DRIFT ... make apply-secrets ENV=staging` and exited non-zero.
- [x] AC2 (a lagging user is not corrected) -> `test_a_stale_user_is_neither_edited_nor_revoked_and_reads_drift`, `test_a_stale_user_does_not_hold_back_the_others`, `test_a_stale_break_glass_user_still_reads_refused`, and `test_review_env_checks_the_idp_first_and_passes_the_lagging_users_on` (the ordering). The same live run gave `grafana operator declared=Admin live=Editor DRIFT Authelia still serves the old groups ...`, not `BOUNDED`.
- [x] AC3 (no hash leaks) -> `757eaa1b`, `test_no_password_hash_reaches_a_finding_even_from_a_malformed_database` plus the `_no_hash_in` check in every AUTH-014 test, with a distinct fake hash per side, and the wiring test asserts no log line holds one.
- [x] AC4 (unreadable Secret) -> `test_an_unreadable_users_secret_is_a_failure_not_a_pass`; `failed` exits 1 (`test_the_command_exits_1_on_every_finding_a_human_must_act_on`). After the first pooled review (FAIL, 2026-09-29): a Secret that is not base64 or not UTF-8, a hung API server (30 s timeout) and a user entry of the wrong shape are all `failed` rather than a crash (`test_a_live_secret_that_cannot_be_decoded_is_a_review_error`, `test_a_malformed_user_entry_is_a_failure_not_a_crash`). With the IdP unread, `APPLY=1` corrects nothing (`test_review_env_corrects_nothing_when_the_idp_cannot_be_read`, from PR-Agent's review).
- [x] AC5 (live) -> 2026-09-29, `make auth-review ENV=staging` and `ENV=prod`: `authelia manu/operator/testuser ... OK` in both, rc=0.

## Test status

- `.venv/bin/pytest -q tests/test_access_review.py`: 55 passed. `mypy` and `ruff` clean on the module and on the test file (the test file's one `var-annotated` error, from AUTH-011, was fixed after the third review).
- Mutation checks, each on a committed tree and restored with `git checkout HEAD`: ignoring `stale` in `reconcile` fails 2 tests; passing `stale` as empty from `review_env` fails 1; passing the PyYAML error text through fails 1.
- Full suite (`make test`): 3017 passed, 15 skipped, 2 xfailed.
- Second pooled review (agy/gemini-3.1-pro-high on `115d7668`): PASS WITH GAPS. Its one gap, `reconcile` at complexity 23 and `review_env` at 17, was raised by this change (from 18 and 14). Fixed in this archive PR by extracting `_hold_back`, `_read_back`, `_review_apps` and `_argocd_findings`: no function in the module is above 15, and the 55 tests pass unchanged. #1918 merged before the review finished, so the fix lands here.

## Third review dispositions (agy/gemini-3.1-pro-high on `f2b3b6db`, PASS WITH GAPS)

- `mypy` error at `tests/test_access_review.py:129`: applied. The empty source is now annotated, and `mypy` is clean on both files.
- Unchecked `## Closing` boxes in `tasks.md`: every item holds (ACs covered by named tests, `features.json` complete, mypy and ruff clean, no scope creep, this file filled in, #1918 opened). The boxes stay as reviewed, because `tasks.md` is a contract file whose digest the archive gate checks against the review.
- A password hash used as a username would be echoed in `user`: declined. That entry would be a malformed users database written by hand, and `apply-secrets` renders usernames from `common.yaml`. The reviewer marked it SPECULATIVE and non-gating.

## Decisions made during implementation

- The comparison is against the users database the declaration RENDERS (`k8s_secrets._build_users_database`), not the raw `users:` list. A user with no password hash in an env is absent from both, so it is never a false drift that `apply-secrets` could not clear.
- A live user the declaration lacks is `drift`, not `undeclared`: `apply-secrets` renders the Secret whole and removes it, while `undeclared` means "never touched" in this module.
- For a lagging user, the review corrects that user in no app, not only Grafana: Gitea's admin flag is also re-derived from the groups at the next login. Chosen by the operator on 2026-09-29.
- The first leak test put its marker at the end of the fake hash, and PyYAML quotes only about 30 characters around the error, so a mutation that leaked the error text survived. The marker now sits where the quote lands.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/identity-secrets/lesson-484-a-reconciler-downstream-of-a-stale-source-reports-a-bound-that-cannot-converge.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a check inside an existing command, with no new contract; how the IdP and the apps it feeds are reconciled belongs to ADR-038, which #1613 revisits
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: seen in one project only; lesson-484 carries it until a second one shows it

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/AUTH-014-idp-groups-drift/` -> `specs/archive/AUTH-014-idp-groups-drift/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
