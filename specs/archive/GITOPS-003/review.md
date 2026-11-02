---
spec: "GITOPS-003"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "a1bb071bb821273083b9e4202ba9fb79e10459a7"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-01"
---

## Adversarial review

**Scope**: GITOPS-003 — the Argo CD → GitHub commit status, `deploy-verify.yml`, the `PostSync`
route probe, `make verify-product`, the delivery watcher, and `specs/GITOPS-003/`.
**Sources**: `specs/GITOPS-003/{proposal,tasks,verification,features}.md`, the 14 commits that
touch this spec under `git log 901fd46904e79b99016fb858b8e7f5efa8c2681a..HEAD -- specs/GITOPS-003`
(`94168bfa`, `fd6ae60e`, `ed3b284e`, `03c6b628`, `a1bfce39`, `4d16f351`, `8582fe59`, `1981f641`,
`f612c91f`, `ab4b58d3`, `2e84df13`, `c93e246f`, `bad6861b`, `a1bb071b`) and the files those commits
change.

**Contract freshness**: `dotf spec digest GITOPS-003` returns the three digests in
`review-request.json` byte for byte (`features.json` `d2bbee2c…`, `proposal.md` `5379e8a8…`,
`tasks.md` `e9aff0b3…`), so this verdict is taken against the current contract, not a stale one.

**Evidence run in this session** (macOS, worktree `.venv`, Python 3.13.16):

```
pytest tests/test_product_verify.py tests/test_argo_wait_status.py tests/test_deploy_verify_workflow.py \
       tests/test_delivery_watcher.py tests/test_k8s_generator_route_probe.py \
       tests/test_argocd_notification_triggers.py -q --no-cov --no-randomly
→ 139 passed, 15.64s        (49 / 21 / 10 / 16 / 19 / 24 — matches features.json f2=47, f3=19, f4=49, f5=24)

pytest tests/test_spec_verifications_select_tests.py -q --no-cov   → 23 passed
   (the guard that reads every active spec's features.json command and collects it;
    GITOPS-003's f2/f3/f6 commands collect, which is why their UNWRITTEN exemptions were removed)

Mutation, product_verify.py: strict `served == expected` → prefix `expected.startswith(served)`
   → 12 failed, 53 passed (restored)
Mutation, hooks.yaml.j2: `"$want"*)` → `"$want"* )` → 19 generator tests unchanged (no effect)
Mutation, delivery-watcher/watch.py: default grace 600 → 60 → 16/16 watcher tests still green
   (restored) — see finding 1
```

`git status --porcelain` is clean apart from this review and the launcher's `review-request.json`;
every mutation was reverted with `git checkout --`. **UNVERIFIED from this session** (no mesh, no
live cluster, no GitHub token): AC1's live statuses, AC4's `make verify-product` runs in both
envs, AC6's `-m infra` live token check, AC2's Loki/Grafana lines, AC3's live staging runs, and
features.json f1/f7 (network/`gh`). Those rest on `verification.md`, whose numbers I could not
re-derive here.

### Spec and task alignment

- All seven ACs are ticked in `proposal.md`, and every AC has an entry in `features.json` with a
  command that either exists or is explicitly live-only. `tasks.md` is fully ticked except the one
  line that is this review (`PRs opened … adversarial-review`), which is correct at this phase.
- The contract and the code agree on the load-bearing words: AC4's five exit codes
  (`Verdict` = 0/1/2/3/4), the "HEAD is read once, a later master is judged by the tag it pins"
  rule (`_judged_revision` + `Superseded` → 4), "health is not a condition"
  (`classify_application` ignores `status.health`), "a payload without `commit` is never a pass"
  (`Served.ABSENT` → `NOT_VERIFIABLE`, after waiting to the deadline), and the eight safety
  properties of the route probe (non-root, read-only root, no SA token, `--connect-to` on
  `traefik.kube-system.svc`, `HookSucceeded`+`BeforeHookCreation`, `activeDeadlineSeconds`,
  ingress-only NetworkPolicy, pinned `curlimages/curl`).
- AC3's descope (the commit comparison moved to AC4) is *declared in the contract* — `proposal.md`
  §3's "Descoped 2026-11-01 (PR3, #2899)" — so the pre-review's first Major is genuinely closed
  rather than quietly dropped.
- AC2 was reworded twice (the sweep is not the bound; the in-cluster watcher is) and the reworded
  text matches `delivery-watcher/watch.py` and `delivery-rules.yaml` line for line, including the
  two behaviours that are easy to get wrong: a GitHub that cannot be asked emits **no** `healthy`
  field (so `unwrap` drops the line and the rule pages as *no data*, never as a broken deploy), and
  a `failure`/`error` status pages at any age.
- `tasks.md`'s closing box "No unrelated changes in the diff (no scope creep)" is true of the 14
  spec commits: they touch the spec, `toolkit/`, `infra/`, `tests/`, `.github/workflows/`,
  `docs/lessons/` and `docs/runbooks/` — no drive-by refactor.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | THEORETICAL | test traceability | The `delivery-watcher` **CronJob manifest is unguarded**: `schedule: */10 * * * *`, `GRACE_SECONDS: "600"` (this *is* AC2's N), `backoffLimit: 0`, and the prod overlay patch `ARGO_ENV: prod` are asserted by no test. Only the script is tested, and it is driven by `env`, so it cannot see the manifest. | Mutating `watch.py`'s *default* grace 600→60 leaves `tests/test_delivery_watcher.py` 16/16 green, which is correct in itself — the test sets `GRACE_SECONDS=600` — but it also shows the constant and the manifest value it mirrors are pinned by nothing. `grep`: no test reads `infra/k8s/base/services/delivery-watcher.yaml` or the prod patch. Consequence if the `ARGO_ENV: prod` patch is ever lost: prod's watcher reads **staging's** status, reports `healthy: 1` while prod is at an older revision, and `gitops003-argo-delivery` never pages — a silent loss of the compensating control AC2 exists for. | UNTESTED | tests |
| Minor | THEORETICAL | injection (workflow commands) | `deploy-verify.yml`'s `on-status` job echoes `${DESCRIPTION}` — Argo's `operationState.message`, written by whatever made the sync fail — into runner stdout, where `::error::`/`::add-mask::`/`::stop-commands::` on its own line are interpreted as workflow commands. Routing `${{ }}` through `env:` correctly stops *shell* injection; it does not stop this one. | `run: echo "::error title=$CONTEXT failed on ${SHA:0:7}::$DESCRIPTION. Runbook: $RUNBOOK"` (`deploy-verify.yml`, on-status step); the description is truncated to 140 chars by the Argo template but may contain a newline. No code execution (the value never reaches a shell unquoted); the impact is a forged annotation or a masked value. | UNTESTED | code (workflow) + tests |
| Minor | SPECULATIVE | correctness (fail-open edge) | The probe's pass condition is a **prefix** match on one concatenated string: `case "$got" in "$want"*)` with `want="400 text/plain"` and `got="<code> <content-type>"`. The prefix is deliberate (`text/plain; charset=utf-8` must pass) but it also accepts `400 text/plainX` and would accept any status sharing a prefix. A delimiter-aware compare (exact, or followed by `;`/space) is exact and equally simple. | `infra/k8s/templates/hooks.yaml.j2` and both rendered `generated/hooks.yaml`; the live forced-failure run in `verification.md` (`405 text/html`) is not a near-miss of this shape. | UNTESTED (no test exercises a `text/plain`-prefixed non-matching content type) | code + tests |
| Minor | SPECULATIVE | consistency | `wait-status` reads the list endpoint `/statuses` (100 per page, newest first) while the watcher deliberately reads the **combined** `/status` to dodge that cap. A commit carrying more than 100 statuses would hide `argocd/kubelab-<env>` and make the sweep and the replay say "no status arrived" falsely. | `argo_manager.wait_status` / `fetch_statuses` vs `watch.py`'s comment ("other contexts can never page Argo's out of the response"). Already declined as speculative in `verification.md`; I re-raise it only because the two readers made opposite choices. | `tests/test_argo_wait_status.py` covers the read path but not a >100-status commit | code (optional) |
| Minor | REAL | spec wording | `proposal.md` §4 has a doubled comma: "in the registry (web is the first),, runnable from any box". | `grep` of `specs/GITOPS-003/proposal.md`. | n/a | spec — **not now**: `proposal.md` is in the contract set, so editing it invalidates this verdict. Carry it as a follow-up ticket if it is worth a round on its own. |
| Question / assumption | — | review scope | The launcher's base `901fd46` is the **merge-base**, so `base...HEAD` is 864 commits / 1887 files / ~193k insertions, of which only 14 commits touch `specs/GITOPS-003/`. The rest is other specs' already-merged work, and it **includes test and script deletions** unrelated to this spec (`tests/test_tfvars_cleanup.py`, `tests/test_provision_fail_closed.py`, `tests/test_sync_homepage_config.py`, `tests/test_configure_oidc.py`, `toolkit/scripts/sync_homepage_config.py`). I reviewed the GITOPS-003-attributable subset and did **not** audit those deletions against their own specs. | `git log --oneline 901fd46..HEAD \| wc -l` → 864; `git diff --stat 901fd46...HEAD -- specs/GITOPS-003` → 4 files, 298 insertions. | n/a | process (not the change) |
| Question / assumption | — | archive gate | `dotf spec archive`'s third pre-flight wants each "Promotion candidates" line answered `yes: <path>` (the path existing) or `no: <reason>`. The lesson line answers `yes:` followed by **three** comma-separated repo paths in one sentence. Whether the parser accepts multiple paths, or only `docs/lessons/` paths with the file present, I could not observe without running the archive (which would rewrite `proposal.md`). | `dotf spec archive --help`; `verification.md` §Promotion candidates. Running `dotf spec archive GITOPS-003` is the only observer, and it is out of a reviewer's scope. | n/a | process |

Nothing above is a Blocker, and nothing above is a **REAL** Major: the one Major is a missing guard
on a seam that is *currently* correct (`infra/k8s/overlays/prod/patches.yaml` does patch
`ARGO_ENV: prod`), and I found no code path that misbehaves today.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | Every AC maps to code that does what the AC says (exit codes, superseded, absent-commit, fail-closed probe); the gaps are negative-path edges at the probe's prefix match and the unwatched manifest. |
| Verification | B | The suite is genuinely non-vacuous (my own prefix-match mutation turned 12 tests red) and the live runs are recorded with commit shas and timestamps; the live half is not reproducible from a session without the mesh, so it stays an assertion I could not re-run. |
| Scope | B | The 14 spec commits are exactly the spec's work, five-plus PRs mapping onto the five ACs; the *reviewable* diff is not isolable (864 commits), so attribution was manual. |
| Reliability | B | Fail-closed throughout — no `healthy` when GitHub is silent, `curl || true` then exit 1, `backoffLimit: 0`, retries on API error distinguished from a failed sync; the workflow-command echo is the one unhardened input. |
| Maintainability | B | Small composable units (`classify_application`, `classify_served`, `_judged_revision`, `verify` with injected clock/sleep), WHY-comments that cite lessons and measurements; `verify()` runs ~55 lines, over the 40-line house rule, and the "why not" is documented but the function is the densest piece here. |
| Handoff-readiness | A | Three lessons landed under `docs/lessons/gitops-delivery/` and `ci-automation/`, the runbook section is linked from the workflow's failure annotations *and* from lesson-407, and the promotion-candidates section answers all three questions with reasons rather than blanks. |

Mechanical aggregation: no D, no C → the rubric path alone would read PASS; one open Major, tagged
THEORETICAL → **PASS WITH GAPS**.

### Verdict

**PASS WITH GAPS**

`dotf spec archive` is **advisable** in this state: the contract digests match, no
`[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in the spec files, and the one Major is a test
gap on a seam that is correct today — it does not describe a wrong behaviour shipping.

Minimum set to flip to PASS (none of it blocking): a test that reads
`infra/k8s/base/services/delivery-watcher.yaml` and the prod patch and asserts the schedule,
`GRACE_SECONDS`, `ARGO_ENV`, `backoffLimit: 0` and the absence of an SA token — the same shape as
the repo's existing manifest guards (`test_image_pull_budget`, `test_networkpolicy_coverage`).

### Recommended next steps

**Contract set is closed** — do not edit `proposal.md`, `tasks.md` or `features.json` now; any edit
invalidates this verdict and spends another round. Everything below lands in `verification.md`
(disposition lines) or in follow-up tickets.

1. **tests** (Major, THEORETICAL, UNTESTED): add `tests/test_delivery_watcher.py` cases that load
   the CronJob manifest and the prod overlay patch and assert `schedule`, `GRACE_SECONDS: "600"`,
   `backoffLimit: 0`, `automountServiceAccountToken: false` and `ARGO_ENV: prod`. Record the
   disposition in `verification.md`.
2. **code** (Minor, workflow-command echo): strip CR/LF from `${DESCRIPTION}` before echoing it, or
   print it with a prefix that cannot begin a workflow command. A one-line change plus a test that
   `tests/test_deploy_verify_workflow.py` asserts the step does not interpolate it raw.
3. **code + tests** (Minor, probe prefix): compare status and media type separately
   (`[ "$code" = "$EXPECT_STATUS" ]` and a `case` on `${ct%%;*}`), so a `text/plainX` answer cannot
   pass.
4. **spec** (Minor, doubled comma in §4): a one-character fix, but not in this round — if it matters,
   file it and let the next spec that touches `proposal.md` carry it.
5. **process** (Question): the review base makes the diff 864 commits of unrelated merged work. For
   a spec that lands over thirteen PRs, a diff scoped to the commits that name the spec
   (`git log -- specs/<id>`) is the reviewable unit; flag it to whoever maintains `dotf spec review`.

Closing-pass disposition for this review itself — Debt: findings 1–3 are tickets-or-fixes, none
applied here (a reviewer does not edit the change). Knowledge: no new repo lesson; the two
observations worth keeping (the manifest seam, the workflow-command echo) are in findings 1 and 2.
Board: the issue stays open until archive, per ADR-018. Review: this file is the review. Evidence:
the commands and their outputs are in "Evidence run in this session" above.
