# Unattended run report: 2026-11-11

- **Armed:** 2026-11-11T07:44:57Z, envelope `f464bbd0`. **Expires:** 19:44:57Z.
- **Objective:** land every IDP-053 slice the agent may merge, and leave the owner-merge slices as triaged, ready PRs.
- **Ended:** around 13:20Z, `reason: queue-empty`. Every remaining eligible item is blocked behind an open owner-merge PR, or behind an owner action (see below).
- **Window coverage:** not continuous. Work stopped from about 08:45Z to 12:00Z, when the session's usage limit was hit (both builders stopped mid-task and resumed after the reset). caffeinate held the host awake throughout.

## Landed under the standing grant

| PR | What | Closes |
|---|---|---|
| #3293 (`aecaa267`) | Registry refuses a private `docker.io` image, and a pull secret missing from the catalog. | #3284, #3292 |

## Ready PRs (owner merges)

All four are triaged, with a `## Review triage` comment each. Only pr-agent reviewed them: CodeRabbit and Codex were at their limits all night.

| PR | Slice | Head | Notes |
|---|---|---|---|
| #3278 | S2a: pull Secret per private registry host | `7fc09fee` | Green. |
| #3283 | S3c: staging zone as a declaration (D8) | `69d301f0` | Green. The pr-agent finding about hardcoded IPs in tests is applied. |
| #3285 | S9: `deploy_shape` provenance through the adapter | `3998cb8f` | Green. The independent adversarial review passed with gaps; those gaps are applied or ticketed. |
| #3281 | S8: prod proof against GHCR or Gitea with the pull credential (agent may merge) | `5093a711` | **Not landed: GitGuardian is red.** See owner actions. The adversarial review passed with gaps: F1–F4 and F6 are applied, F5 is ticketed. |

## Owner actions

1. **#3281 GitGuardian.** Two "secrets" are synthetic login tuples in the first commit's test fixture, already replaced in the tree. Classify both incidents as false positives in dashboard.gitguardian.com (see lesson-723). Then the PR can land under the grant, or you can merge it yourself.
2. **Merge #3278, #3283 and #3285** after reading them. #3285 changes the merge judge.
3. **Decide resume's prod hostname.** D8/AC13 (#3283) require `staging.<prod>` once prod is declared. A product without its own domain that declares prod under `kubelab.live` therefore needs a new staging zone. D8 does not say what that product's prod hostname is.
4. **Decide the promotion credential (#3286).** `promote-prod.yml` has no pull token, so any private product's prod promotion is refused. The ticket lists options A, B and C; A is recommended.
5. **Pick the CronJob command (resume#777, on the forge).** Option A, a `resume daily` subcommand, is recommended. The container-port question is answered by the contract: `port` belongs to the product, and resume's is 8765.
6. **Accept ADR-073.** It still has two items before acceptance: the D2 verification debt and the D13 (A)/(B) choice. resume's claims (volume, job, `forwardauth-admins`, `fs_group`) are filed only after acceptance, per your 2026-11-04 comment on #2449. That is why no claims-engine spec was opened.
7. **Answer an open question from yesterday.** #3252 and #3256 were merged under your login while this session was out at its usage limit. Was that you?
8. **Delete a stale branch.** The local branch `docs/idp-053-forge-agnostic-product-path` holds unpushed commit `55b58cfa`. It predates the D8 ruling (#3137) and is superseded, so it can be deleted.

## Tickets filed

- **kubelab:**
  - #3272: `tag_exists` reports a Docker Hub 5xx as a missing tag.
  - #3276: ACME zones from `zones.json`.
  - #3284 and #3292: closed by #3293.
  - #3286: promotion credential.
  - #3287: one bearer per proof.
  - #3288: Gitea outage verdict split.
  - #3289: deploy-shape Gitea wiring.
  - #3297: wire the catalog check into `pull_secret_mappings` after #3278.
- **resume (forge):** #777, the daily command.
- **Comments:**
  - #2612: the `GITEA_URL` and `GITEA_REPO_READER_TOKEN` contract.
  - #2366: status.
  - resume#688: port answer, daily-command pointer, and a correction (claims wait on ADR-073).

## Why the queue is empty

- #3272, #3287: touch `registry.py` and `product_release.py`, which are held by #3281.
- #3288: touches `deploy_shape.py`, which is held by #3285 and frozen by the envelope.
- #3297: depends on #3278.
- Every remaining IDP-053 slice is owner-merge or gated (S2b, S2c, S3b, S4, S5c, S6b, S7).

## Noted, not ticketed

- The S8 builder saw two tests fail once under heavy load, and both pass alone: `test_edge_shape_check::test_the_probe_writes_one_line_per_connect` and `test_r2_backup_freshness_rule::test_the_harness_reads_the_existing_health_rule_both_ways`. They were not reproduced, so they need watching rather than a ticket.
