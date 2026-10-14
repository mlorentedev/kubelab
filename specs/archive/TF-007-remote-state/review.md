---
spec: "TF-007-remote-state"
verdict: "PASS"
reviewed_sha: "e61f2320df6077307f04fb5c50317f5eff315254"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-14"
---

## Adversarial review

**Scope**: TF-007-remote-state (whole change, `git diff 1b900c229807e6cbc4eca18ec037edd7801c3fee...HEAD`)
**Sources**: `specs/TF-007-remote-state/{proposal,tasks,verification,features}.md|json`; diff of 93 files (+4990/-1434) covering the runner refactor (PR 1a), the R2 backend (PR 1b), and merges from `origin/master` (deps/CI bumps) carried by the branch.

### Verification performed in this session (evidence, not claims)

- `poetry run pytest tests/test_terraform_runner.py tests/test_terraform_single_entry.py tests/test_terraform_backend.py tests/test_terraform_state_bootstrap.py tests/test_terraform_plan_guard.py tests/test_vps_firewall_tfvars.py` → **285 passed**, exit 0.
- Full suite `poetry run pytest tests -q --no-cov` → **4723 passed, 3 failed, 18 skipped, 2 xfailed**; the 3 failures are pre-existing/environmental (finding 5 below, base-reproduced).
- **Six mutations, each reverted, each RED against a green baseline**:
  - raw `terraform plan` line added to `tf-dns-plan` recipe → `test_terraform_single_entry.py`: 1 failed (AC3).
  - `dns` root `backend "s3"` → `backend "local"` → `test_terraform_backend.py`: `test_each_root_declares_only_its_key_in_an_s3_backend[dns]`, `test_no_terraform_file_anywhere_declares_a_local_backend` failed (AC1).
  - rendered tfvars/private copies `0o600` → `0o644` → `test_the_rendered_tfvars_exists_while_terraform_runs_private_and_outside_the_module`, `test_the_downloaded_copy_is_private_before_the_cli_writes_it_and_gone_after` failed (AC4).
  - unrecovered-state guard disabled (`if root.unrecovered …` → `if False …`) → `test_a_lost_state_refuses_every_write_and_names_its_ticket` failed for apply/destroy/untaint/restore (AC4/TF-015 refusal).
  - `TemporaryDirectory` made to never clean up → `test_the_private_directory_never_outlives_the_run` failed (6 tests) — this is the retained proof for the **deleted** `tests/test_tfvars_cleanup.py` (see below).
  - `_remove_legacy_renders` stubbed to `return` → `test_a_stale_rendered_file_in_the_module_is_removed_first` failed.
- `bash scripts/check-lessons.sh` → OK (565 lessons), exit 0.
- `make secrets-audit` → exits 1 (finding 1; orphan pre-existing at base, verified).
- `ruff check` over all changed `.py` files → clean except one F841 in `tests/test_gcp_hub_module.py:701` that **exists at the base commit** (verified via `git show`). Repo-wide `ruff check toolkit tests` reports 50 errors, all in files untouched by this diff (pre-existing / ruff 0.17 bump from master). `C901 max-complexity = 10` is selected and passes on the new code.
- Live AC5/AC6/AC7 evidence (bootstrap, migrate of dns/r2/aws from msi, `No changes` plans from the Mac, `test-tfstate-lock-live`) is recorded in `verification.md` with dates, commit ids, lineages and serials. It requires the operator's msi checkout and live credentials, so it was **not re-run by this reviewer**; recorded-live, treated as documented evidence.

### Spec and task alignment

- **AC1** → 8 roots declare `backend "s3"` only (grep confirmed), `tests/test_terraform_backend.py` (mutation-verified above). ✅
- **AC2** → committed `infra/terraform/backend.s3.tfbackend` equals the render of `terraform.state` in `common.yaml`; no credential, no `encrypt` (backend tests green; file inspected). ✅
- **AC3** → `tests/test_terraform_single_entry.py` (Makefile recipes, toolkit AST scan, one `$(_TF)` line per target); mutation-verified; repo-wide grep found no `terraform` invocation in `scripts/`, `.github/` or `infra/ansible/`. ✅
- **AC4** → `tests/test_terraform_runner.py` (107 tests) + plan-guard + vps-firewall tests; init-first, env allowlist (inherited `AWS_*`/`TF_*` stripped except plugin cache), 0600 temp dir removed on success/failure, exit-code propagation, per-root apply mode, secrets only as `TF_VAR_*` in the child env — mutation-verified. Renderers (`gcp_tfvars`, `r2_tfvars`, `vps_firewall_tfvars`, `_render_dns`) write no secret to the tfvars file (inspected). ✅
- **AC5/AC6** → `tests/test_terraform_state_bootstrap.py` (idempotent bucket/lock/token, consequence check on backup bucket) + live record in `verification.md`. ✅ (live recorded)
- **AC7** → migrate content gate (`_arrived`, `_differing`), no-`-force` push, rename to `terraform.pre-remote.tfstate`, second-run no-op — 20 named migrate tests; live record for dns(14)/r2(2)/aws(0). ✅ (live recorded)
- **AC8** → history before/after snapshots with create-only put, locked-prefix tolerance, serial-0 skip — named history tests + live `tf-state-history` record. ✅
- **AC9** → `terraform.state.*` and `aws.*` present in `SECRET_CATALOG`; `test_every_secret_a_run_requires_exists_in_sops` green. `make secrets-audit` does **not** exit 0 in this tree — see finding 1 (disclosed, pre-existing, ticketed). ⚠️
- **AC10** → `docs/adr/adr-069-…`, `docs/runbooks/terraform-state.md` (bootstrap, migrate, restore, force-unlock, rotate, troubleshooting table all present), lessons 564/566, `check-lessons.sh` OK. ✅
- **Test deletion**: `tests/test_tfvars_cleanup.py` (added `94f7676e` for TOOL-039) deleted in `fb8e82a8`. Retention bar, all five fields: (1) it executed Make recipes with a stub `terraform` to prove rendered tfvars are removed after a failed plan and the failure reaches the caller; (2) remaining proof **shown** — mutation "temp dir never cleaned" → `test_the_private_directory_never_outlives_the_run` red, mutation "legacy render removal disabled" → `test_a_stale_rendered_file_in_the_module_is_removed_first` red; (3) seam unlocked is the per-target Makefile `_exit` cleanup dance — no non-test callers, production code removed is exactly those recipe lines; (4) history: introduced for TOOL-039 (docstring quotes the incident), rationale in commit `fb8e82a8`; (5) focused command: `poetry run pytest tests/test_terraform_runner.py -k 'private or outlives or stale or legacy'`. Bar met.
- No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in any spec file (grep: none).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | AC9 | `make secrets-audit` exits 1 here (`make: *** [secrets-audit] Error 1`), while AC9 says it "passes". The orphan `apps.services.automation.n8n.sale_digest.site_tag` exists at the base commit too (`git show 1b900c22:infra/config/secrets/prod.enc.yaml` contains `site_tag`), is disclosed in `verification.md`, and is ticketed as SEC-031 #2240. | this session's `make secrets-audit` run + base-tree grep | `make secrets-audit` (the named gate itself) | follow-up ticket already exists; disposition in `verification.md` — do not reword `proposal.md` (contract set) |
| Minor | REAL | spec/tasks | `tasks.md` still has one unchecked box: "Draft PR with `## Knowledge`; triage; `## Review triage`" — the only open task; every implementation box is ticked with diff/test evidence. | `tasks.md` | n/a | spec artifacts; ticking checkboxes is excluded from the staleness digest (SDD-042), so complete the step and tick — rewording would not be |
| Minor | REAL | spec | All ten AC checkboxes in `proposal.md` read `- [ ]` while `features.json` marks all ten `state: passing` — the human-readable contract lags the machine list. | `proposal.md` vs `features.json` | n/a | spec artifacts; tick (ignored by staleness) or leave; no rewording alongside this verdict |
| Minor | THEORETICAL | spec wording | Proposal §What writes `make tf-state-restore TO=…` and `make tf-state-unlock LOCK=…`; both targets also require `ROOT=` (Makefile recipes; runbook documents `ROOT=dns` correctly at lines 104/118). Shorthand only — no operator can hit it while following the runbook. | Makefile `tf-state-restore`/`tf-state-unlock` recipes | n/a (runbook is correct) | contract set — disposition in `verification.md`; do not edit `proposal.md` under this PASS |
| Minor | REAL | test env | Full suite has 3 failures: `test_access_review.py::test_argo_cd_rbac_lets_users_operate_and_never_administer` **reproduced failing at base** `1b900c22` in an isolated worktree (pre-existing), and `test_oauth_tokens_not_logged.py` vector tests fail on a docker invocation (`Is a directory (os error 21)`); neither file nor the vector configs are in this diff. `verification.md`'s "fails only in the files master fails on macOS" claim is consistent with this. | base-worktree rerun, this session | `test_argo_cd_rbac_lets_users_operate_and_never_administer` | none for this spec (pre-existing; vector/docker one UNVERIFIED at base, environmental by inspection) |
| Minor | THEORETICAL | code resilience | `_restore` reads `current["serial"]` by key while every sibling path uses `.get(...,0)`; a remote state JSON lacking `serial` (hand-edited or corrupt) raises a bare `KeyError` instead of a `RunnerError` naming the fix. Terraform-produced states always carry `serial`, so no observed path. | code read of `toolkit/features/terraform_runner.py::_restore` | UNTESTED | code (one-line defensive `.get`) — follow-up, does not gate |
| Minor | REAL | code quality | Five new functions exceed the repo's <40-line rule: `run` (51), `_run_in` (58), `_migrate` (47), `bootstrap` (42), `tf_killswitch_prove` (50). Cyclomatic complexity is within the stated cap (ruff `C901 max-complexity 10` clean on changed files). The file's own structure and comment density keep them readable. | AST line counts this session; `ruff check` output | n/a | code — follow-up refactor, does not gate |

**Code-level checklist walk**: no injection (every external call is `subprocess.run` with list argv, no shell; `restore`/`unlock` inputs regex- or length-validated); no hardcoded secrets (SOPS-only; `common.enc.yaml` diff is encrypted blobs, the added `terraform.state.*` pair is `ENC[...]`); auth/secret handling is the strongest part of the change (child env allowlist, 0600 temp dir, private `state pull` never printed, `state show` deliberately not offered); no blocking-in-async paths (CLI tool); error paths are explicit `RunnerError`s with remediation text; `history` puts are create-only under a bucket lock, and the before-snapshot gate stops a write when history is unreachable.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All ten ACs verified with named tests + six reviewer mutations red; AC9's audit exits non-zero (pre-existing, disclosed, ticketed) is the one literal gap. |
| Verification       | B | Every `features.json` entry reproduces (commands run this session, 285 green, mutations red); live AC5/AC6/AC7 evidence is detailed but needs msi/credentials context, so it is recorded-live and not reviewer-reproducible. |
| Scope              | B | Diff matches the two-PR delivery plan; branch merges carried master's deps/CI bumps and supporting fixes (#2235/#2237/#2238) — documented in tasks/verification as lessons, but they are side-changes beyond the proposal. |
| Reliability        | B | Error paths, kill-resume, push refusals, history-gate failures and rollback of staged state all handled and tested; one theoretical KeyError path in `_restore`. |
| Maintainability    | B | ruff + `C901 ≤10` clean, extensive docstrings explaining WHY, no dead code; five functions over the repo's 40-line rule. |
| Handoff-readiness  | A | ADR-069, runbook with troubleshooting table, four lessons, CLAUDE.md gotcha, README/runbook pointer updates, spec trio + features.json all land in the same change. |

Aggregation: no D, no C → all B or above → PASS on the rubric axis. Severity axis: no Blocker, no Major → PASS.

### Verdict
PASS

### Recommended next steps

- Disposition findings 1–4 in `verification.md` (outside the contract set): the secrets-audit orphan stays tracked under SEC-031 #2240; tick the remaining `tasks.md` box and the `proposal.md` AC boxes when the PR step completes — checkbox ticks are excluded from the staleness digest (SDD-042), rewording is not.
- Findings 6–7 are code-set follow-ups (defensive `.get("serial")` in `_restore`; function-size split) that can land in a later PR without invalidating this review; file or fix per the `track-or-fix` standing order.
- `dotf spec archive` is **advisable** once the last `tasks.md` box (PR draft/triage) is done and ticked. No FAIL actions; no contract-set edits requested under this verdict.

## Second review (2026-10-14, reviewer persona, before merge)

An independent second pass on the merged branch, `565a829c`. It ran 39 mutations (31 RED) and found no path that loses, forks or overwrites state. Each finding was then applied, ticketed or declined. The fixes (`889be610`) were reviewed again as a delta. The last commit (`30fa50b6`) applies that delta review, and the mutants listed below prove it.

| # | Finding | Disposition |
|---|---|---|
| 1 | A failed `state pull` was untested: dropping its `raise` kept every test green, and an outage would read as "no state" | Applied. `test_a_backend_that_cannot_be_read_stops_every_write[apply,migrate,restore]`; mutant RED |
| 2 | `Closes #554` overstated: only presence of the token is checked, not validity | Applied in the PR body; #554 is referenced, not closed |
| 3 | A hardcoded history bucket or prefix kept the tests green | Applied. `test_history_goes_to_the_bucket_and_prefix_common_yaml_names`; mutant RED |
| 4 | The retention lock was described as unbreakable; the `kept` token branch is not re-proved | Runbook corrected; the token proof is TF-019 (#2245) item 4 |
| 5 | History copies are taken at run boundaries, not on every serial | Runbook says so |
| 6 | `state push` may skip its lineage check against a remote with no resources | Applied. The runner refuses any written remote with other content before pushing: `test_migrate_never_pushes_over_a_state_r2_already_holds`; mutant RED |
| 7 | `-lock=false` passed through | Applied. Refused, while a bare `-lock`, `-lock=true` and `-lock-timeout` still run (both directions tested); mutants RED |
| 8 | `output()` turns a read failure into "state lost" | TF-019 (#2245) item 3 |
| 9 | Old worktrees still on `backend "local"` | Noted in the PR body for after the merge |
| 10 | Two comments left above the wrong block | Moved |

Delta review verdict on `889be610`: mergeable once the runbook's stale migration sentence is fixed. That sentence, the bare-`-lock` over-refusal and the missing allowed-flag tests are fixed in `30fa50b6`.
