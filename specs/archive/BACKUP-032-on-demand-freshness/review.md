---
spec: "BACKUP-032-on-demand-freshness"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "805f67d6326c352fe4b7d4b234ef6c41d9e02c36"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-03"
---

## Adversarial review

**Scope**: BACKUP-032-on-demand-freshness, whole change `a75c605f6cf9ed7eb58b676e4a58b83f6861322d...805f67d6326c352fe4b7d4b234ef6c41d9e02c36` (base as resolved by the launcher; not substituted)
**Sources**: `specs/BACKUP-032-on-demand-freshness/{proposal.md,tasks.md,verification.md,features.json}`, `git diff a75c605f...HEAD` (44 files, +1995/−51), `git log a75c605f..HEAD` (10 commits), and a live read of prod Loki/Grafana logs on 2026-10-03

### Spec and task alignment

- **AC1** (probe emits `newest_snapshot`, `snapshot_age_seconds`, `reachable`, `class`; null on restic failure) → `tests/test_r2_backup_watcher_probe.py`: `test_each_node_reports_its_newest_snapshot_age_reachability_and_class`, `test_the_snapshot_time_is_converted_to_utc_from_any_offset`, `test_the_newest_of_several_snapshots_is_the_one_reported`, `test_no_snapshot_to_read_is_null_never_a_fresh_looking_age`, `test_an_unparseable_snapshot_time_is_null_and_fails_the_node`. **Re-run: 84 passed** (f1 green).
- **AC2** (freshness rule fires/silences per fixture lines) → `tests/test_r2_backup_freshness_rule.py`: `test_a_reachable_on_demand_node_that_stopped_shipping_fires`, `test_the_freshness_rule_stays_silent[*]` (off, turned off, fresh, always-on), `test_every_on_demand_node_off_is_a_zero_never_no_data`, `test_each_on_demand_node_is_judged_on_its_own`, evaluated in the pinned `grafana/loki:3.6.4` with the expr read from the rules YAML. **Re-run: 19 passed** (f2 green). The Grafana `for: 7h` state machine itself is not executed end to end — a **declared Limit** in `proposal.md` (Risks), pinned statically by `test_the_freshness_rule_waits_for_two_probes_and_judges_only_on_demand_nodes` and `test_the_alert_windows_follow_the_cadences_they_depend_on`.
- **AC3** → `test_the_shrink_rule_fires_only_on_a_drop_of_more_than_half[*]` (incl. `null` size), `test_a_single_probe_never_reads_as_a_shrink`, `test_nodes_of_different_sizes_never_read_as_a_shrink`. **Re-run with `-k shrink`: 7 passed** (f3 green).
- **AC4** → `tests/test_r2_watcher_targets.py` (`test_every_node_carries_its_tailscale_ip_probe_port_and_class`, `test_a_per_node_port_overrides_the_default`, `test_a_node_without_an_address_or_a_class_refuses_to_render`). **Re-run: `poetry run toolkit sync r2-watcher-targets --check` rc=0; `make validate-sync` rc=0** (f4 green).
- **AC5** → recorded in `verification.md` (prod watcher run 2026-10-02, per-node `reachable=1` + numeric ages, `node_backup` tasks changed: 0 on both nodes) and gated by f5. **Re-run: f5 rc=0.** Corroborated live this run: prod Grafana is evaluating `rule_uid=backup032-on-demand-freshness` and `rule_uid=backup032-r2-backup-shrink` every 10 minutes with expressions byte-matching HEAD's YAML (Loki/Grafana log lines at 2026-10-03T22:39/22:49, `class=\`on-demand\`` on both operands, `by (backup_node)`, 7h/9h windows). The per-node probe values themselves are a point-in-time prod observation — recorded, not re-executed by me.
- **AC6** → `test_an_always_on_node_the_probe_cannot_reach_fails_the_fleet[*]`, `test_an_on_demand_node_that_is_off_stays_healthy`. **Re-run `-k always_on`: 4 passed** (f6 green).
- **Tasks**: every `[x]` I could check has diff or command evidence; the single unchecked box is the review itself (this artifact). Runbook anchors `#on-demand-backup-stale` and `#r2-backup-shrank` exist (`docs/runbooks/offsite-backup-restore.md:176,204`). No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in any spec file. Launcher-recorded `contract_digests` correspond to HEAD; the contract set was untouched during this review (only the launcher's own `review-request.json` is untracked).

**Verification evidence produced in this run** (all commands re-run fresh):

| Command | Result |
|---|---|
| `make test` | **3615 passed, 16 skipped, 154 deselected, 2 xfailed, rc=0** (8m00s) |
| `make lint` | rc=0 (ruff clean, 118 files formatted) |
| `make validate-sync` | rc=0 (all generated files in sync) |
| f1–f6 verification commands | all rc=0 (counts above) |
| Mutation 1: delete both `class=\`on-demand\`` filters from the freshness rule | **3 red** (`stays_silent[always-on and stale]`, `zero_never_no_data`, static pin) — reverted |
| Mutation 2: probe `reachable=0` init → `reachable=1` | **9 red** (6 probe tests + 3 freshness tests) — reverted |
| Mutation 3: hand-edit `targets.txt` IP | f4 `--check` rc=1 (stale) — reverted |
| `toolkit obs logs --env prod` | prod Grafana actively evaluating both backup032 rules with HEAD's expressions |
| Secrets scan of full diff | none added (test credentials are `not-a-real-value-fixture` markers) |

Working tree is clean apart from the launcher's `review-request.json`; every mutation was reverted and re-checked with `git status`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec/tasks accuracy | `tasks.md` closing box "No unrelated changes in the diff ✓" is inaccurate **as scoped**: `a75c605f...HEAD` also carries five merged PRs unrelated to BACKUP-032 (#1960 act-runner cache, #2032 credentials wording, #2036 rpi3 kuma, #2040 other lanes' lessons, #2042 staging web sha). The spec's own five commits (f651d313, a19f5a2e, da13afc6, 6ad0c6c7, 805f67d6) are verified clean — the claim is true of them, not of the stated diff | `git log a75c605f..HEAD` + diff stat: `infra/ansible/`, `toolkit/features/credentials.py`, `staging.yaml` all change outside the spec | UNTESTED (no test governs a checkbox's wording) | spec — disposition in `verification.md` (contract set stays closed: state that the box means "this spec's own commits", or ticket it; do NOT edit `tasks.md` alongside this verdict) |
| Minor | REAL | spec/features accuracy | `features.json` f2 evidence reads "18 passed" but HEAD has 19 tests — 805f67d6 added `test_the_alert_windows_follow_the_cadences_they_depend_on` after that capture. The command itself passes (19 passed), so the entry is stale, not false | I ran f2's exact command: `19 passed in 20.51s` vs evidence text "18 passed" | `tests/test_r2_backup_freshness_rule.py` (all 19 green) | spec — `features.json` is contract; refresh via the harness's next evidence capture, or record the discrepancy in a `verification.md` disposition |
| Minor | THEORETICAL | alerting/shrink | If a watcher run is missed (backoffLimit: 0, no retry until the next slot), the 9 h window then spans probes ~12 h apart, so "consecutive" becomes "consecutive *available*": a genuine multi-hour shrink could page a window later than the 6 h premise argues, and the shrink window's > probe-interval static pin does not cover the gap case. Self-heals on the next successful run | code read: rule expr `[9h]` vs CronJob `0 */6` + `backoffLimit: 0` (`r2-backup-watcher.yaml:52,61`); no reproduction attempted | UNTESTED (no missed-probe fixture case exists) | tests (surface only; add a fixture case if a false page is ever observed — not archive-blocking) |
| Question / assumption | THEORETICAL | alerting/freshness | AC2's "two consecutive probes" is enforced by Grafana's `for: 7h` pending state, which the LogQL harness cannot execute. This is a **declared Limit** in `proposal.md` (Risks), compensated by two static pins that derive the cadences from the CronJob `schedule:` and `node_backup_interval` rather than retyping them | `proposal.md` Risks "Limit"; `tests/test_r2_backup_freshness_rule.py::test_the_freshness_rule_waits_for_two_probes_and_judges_only_on_demand_nodes`, `::test_the_alert_windows_follow_the_cadences_they_depend_on` | Static pin only — Grafana state machine UNTESTED (accepted in the contract) | spec — already dispositioned in `proposal.md`; no action |

No Blocker and no Major found. The failure modes I argued hardest against were all closed by a named test or a fail-closed path: unreadable snapshot time → `snapshot time unreadable` + unhealthy (never age 0); restic failure → `null` age, dropped by `unwrap`, health rule pages instead (one cause, one page); all on-demand nodes off → product 0, never `noDataState`; always-on unreachable → fleet unhealthy; missing `tailscale_ip`/`location` → renderer raises; hand-edited `targets.txt` → `--check` rc=1; Vector's `node` stream-label collision → `backup_node` extraction, proven by cross-node tests that go red on the pre-fix rules.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All six ACs met with extensive negative-path coverage and three red-green mutations proving the tests bite; held back from A only by the Grafana `for:` state machine being a declared-but-unexecuted part of AC2 |
| Verification       | B | f1–f6, `make test`/`lint`/`validate-sync` all re-run green this run with outputs, plus live prod rule-evaluation corroboration; AC5's per-node numbers rest on a recorded prod run gated by a prose parse (f5), not re-executable |
| Scope              | B | The spec's own five commits touch only spec work (verified per-commit stat); five unrelated merged PRs ride in the launcher's scope but each is transparently named by its PR number in its commit subject |
| Reliability        | A | Every probe error path is fail-closed with a named test (null time, unreadable repo, nc hang/timeout via `timeout`, stats failure, missing targets); `noDataState` annotation names both causes; disclosed reachability risk has an always-on positive control |
| Maintainability    | B | Small functions, shellcheck-justified exceptions explained, comments carry the WHY; held back from A by the probe's main loop growing to ~120 lines (pre-existing script shape) |
| Handoff-readiness  | B | Spec triad current, lessons 509/510/512 present and indexed, runbook sections with matching anchors, prior review dispositions recorded; held back from A by the two spec-accuracy nits (F1, F2) above |

Aggregation: no D, no C → no rubric-forced downgrade; findings are minors only → **PASS WITH GAPS**.

### Verdict

**PASS WITH GAPS** — no blockers, no majors; three Minor findings (two REAL documentation-accuracy nits, one THEORETICAL alerting edge) and one declared-limitation Question, each with a disposition line below. Severity × reality: nothing here rises to a REAL Major, and the sole Blocker candidates I could construct (label grouping, null handling, all-off state, drift) were each defeated by a named test I re-ran or by a mutation I performed and reverted.

### Recommended next steps

Contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed by this verdict** — no contract edits are requested, and none should accompany it. Route the dispositions through `verification.md` (excluded from the staleness check) or a follow-up ticket:

1. **F1 (spec)** — add one disposition line to `verification.md`: the "No unrelated changes" box refers to this spec's own commits; the scoped diff also carries #1960/#2032/#2036/#2040/#2042, each already merged through its own reviewed PR. Applied, ticketed, or declined with a reason.
2. **F2 (spec)** — let the harness's next evidence capture refresh f2's count (18 → 19), or note the stale count in a `verification.md` disposition. The f2 command passes today; nothing is masked.
3. **F3 (tests, follow-up)** — optional: a fixture case with a missed probe run, if a shrink page is ever traced to a >6 h span. Not archive-blocking (THEORETICAL, self-healing).
4. **F4** — no action; the `for:` limitation is already declared and statically pinned in the contract.
5. **Knowledge/Board (DoD)** — lessons exist (`docs/lessons/observability/lesson-509|510|512-*`), runbook sections exist, issue #485 is OPEN and assigned (closes with the change that closes it). Evidence: this run's command table above.

**Archive**: `dotf spec archive BACKUP-032-on-demand-freshness` is **advisable** in this state — the review is fresh (frontmatter sha = HEAD, contract set untouched), the verdict passes, and the gaps are tracked rather than open. (No FAIL, so no minimum-flip set applies.)
