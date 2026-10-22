---
tags: [spec, verification, templates]
created: "2026-10-16"
---

# Verification - OPS-038-gitea-forge-upgrade

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

| AC | Status | Proof |
|----|--------|-------|
| AC1, the 1.27.3 image starts on the restored snapshot | Met | Pin `gitea/gitea:1.27.3` at `common.yaml:1003` (#2381, `1bf91076`). The drill passed on snapshot `13893d74` on 1.25.5 (baseline) and 1.27.3, recorded on #2375 (issuecomment-6230892745). The drill needs ace2 and R2 and was not re-run for this archive |
| AC2, doctor clean, `PUBLIC_URL_DETECTION` pinned | Met, with a baseline exclusion | `legacy` is pinned in the compose template and `tests/test_gitea_public_url_pin.py` asserts it (#2381). The doctor probe is `toolkit/features/gitea_upgrade_probe.py` (#2379, `809a9269`). `Garbage collect LFS` errors on 1.25.5 and 1.27.3 alike and is excluded by name as a measured baseline (lesson-586); #2408 (`2e2587ca`) removed the stale-merge-base exclusion once 1.27.3 had fixed it |
| AC3, the `dotf forge` REST contract | Met | The contract probe (issue create, comment with `html_url`, edit) passed on the restored copy on both versions (#2379, lesson-586). Pull create/comment/edit was not exercised on the live forge |
| AC4, OIDC login and `update-oauth` | Met, on the live forge | The drill has no network, so this was checked live (runbook step 2.4). #2375 issuecomment-6231535448 records the OIDC login verified on 1.27.3, and `update-oauth` runs inside `TAGS=gitea` provisioning, which finished `changed=0` on re-run |
| AC5, merge settings and the PR-Agent app | Partial | Merge settings applied and read back on the restored copy on both versions (#2379). **Not shown:** the PR-Agent app (`pragent/pr-agent:0.45.0-gitea_app`) against 1.27.3; #2375 issuecomment-6230892745 lists it as not yet verified and nothing later records it. Carried to #1823 (issuecomment-6331149403) |
| AC6, runner token and act_runner 0.2.13 | Met | Run 1521 on `personal/imagesensortool` succeeded on act_runner 0.2.13 against 1.27.3 (#2375 issuecomment-6238815197); `gitea-prune-runners` found 1 runner, all declared. OPS-034 then moved the runner to `gitea/runner` 4.1.0 (#2425, `b2f13282`) |
| AC7, live upgrade through provision, `changed=0` | Met | Fresh backup snapshot `13893d74`; `make provision NODE=bee ENV=prod TAGS=gitea` `changed=4`, then `changed=0`; `/api/healthz` 200; `tests/infra/test_gitea_anonymous_surface_live.py` 5 passed (#2375 issuecomment-6230892745) |
| AC8, a second push cancels the first run | Not met, carried | Only pickup and parsing of a `concurrency` block were measured (run 1521). The cancel half, queued and running, moves to #2619 (OPS-045), open (an earlier draft named #2063, OPS-034, which is about leaked job volumes and does not hold the measurement; archive review round 1). No forge workflow declares `concurrency` yet. Operator decision 2026-10-22 |
| AC9, runbook and lesson | Met | `docs/runbooks/gitea-upgrade.md` and `docs/lessons/storage-backup/lesson-586-an-upgrade-probe-needs-the-same-run-on-the-deployed-version.md` (#2381) |

## Test status

- Test suite: `poetry run pytest -q --no-cov tests/test_gitea_upgrade_probe.py tests/test_gitea_public_url_pin.py tests/test_gitea_drill.py tests/test_gitea_actions_runner.py tests/test_gitea_anonymous_surface.py` -> 74 passed (2026-10-22, from the worktree root)
- Manual smoke test: the live upgrade and the runner pickup, as recorded per AC above and on #2375
- No regressions in existing test suite: yes for the files above; this archive changes only the spec folder

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- Target 1.27.3, not 1.26.x or 28.x: see `proposal.md` What. The rehearsal showed skipping two minors was safe on our data.
- The first doctor failure on 1.27.3 was a pre-existing 1.25.5 defect; the probe is judged against the deployed version, not in absolute terms (lesson-586).
- The cancel half of the goal was not measured before archive and moves to OPS-045 (#2619) (an earlier draft named #2063, OPS-034, which is about leaked job volumes and does not hold the measurement; archive review round 1), because cancelling a running job needs the runner upgrade, which landed as #2425 after this work.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/storage-backup/lesson-586-an-upgrade-probe-needs-the-same-run-on-the-deployed-version.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a version bump through the existing IaC path, with the procedure in docs/runbooks/gitea-upgrade.md
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: one project

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/OPS-038-gitea-forge-upgrade/` -> `specs/archive/OPS-038-gitea-forge-upgrade/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)

## Archive review dispositions (round 1, `nan/qwen3.8-flash`, FAIL)

- Major, AC8 unmet: carried to #2619 (OPS-045), which holds the `concurrency:` block and the two-push measurement. #2375 stays open until #2619 lands.
- Major, wrong carry target: corrected. #2063 is about leaked job volumes; every reference now names #2619.
- Major (theoretical), `KNOWN_BASELINE_FAILURES` can widen silently: ticketed as #2620 (TOOL-124).
- Minor, four `features.json` verifications are prose, not commands: declined for this archive. They are live checks with no command form (OIDC login, runner pickup, provision `changed=0`). f4, f6 and f7 record `passing` asserted from live records on #2375, not from an exit code.
- Minor, f5 said "No ticket tracks this check": corrected to #1823 (issuecomment-6331149403).
- Minor, PR-Agent never checked against 1.27.3: carried to #1823.
- Minor (theoretical), no version-floor test, and a literal pin in `tests/test_gitea_anonymous_surface.py`: ticketed as #2620 (TOOL-124).
- Minor (speculative), runbook ordering of `sync-platform-json` and provision: declined. The reviewer marked it surface-only and did not reproduce it.
- Minor, review base bundles unrelated PRs: a launcher artifact, outside this repository.

## Archive review dispositions (round 2, `nan/glm5.3-flash`, PASS-WITH-GAPS)

- Minor, f8's evidence still ended with "move this half to #2063": corrected to #2619.
- Minor, f4/f6/f7 asserted from live records, the unenforced guards, and the PR-Agent half: unchanged from round 1 (declined, #2620 and #1823 respectively).
