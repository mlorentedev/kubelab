---
spec: "AI-013-hermes-liveness"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "54134be789b5ad201a46da1ae531428f2eef5e62"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-14"
---

## Adversarial review

**Scope**: AI-013-hermes-liveness (bitácora mlorentedev/kubelab#2175), round 6
**Sources**: `specs/AI-013-hermes-liveness/{proposal,tasks,verification,features.json}`;
`git diff 338fc72f46254ee92d05964bbad6187a4db70b64...HEAD` (17 first-parent non-merge commits, 12 of them
the spec's own; the rest arrived through master merges and are judged only where they interact);
`tests/test_hermes_liveness.py`, `infra/ansible/roles/agent_stack/{files/hermes-liveness.sh,tasks/hermes.yml,templates/*}`,
`docs/runbooks/hermes-kubelab.md`, `docs/lessons/observability/lesson-759-*.md`.

**What I executed in this worktree (fresh, no build artifacts at start)**

| Check | Result |
|---|---|
| `pytest -q tests/test_hermes_liveness.py` | **27 passed** |
| Mutation: `restart_count -le 1` → `-le 2` in `hermes-liveness.sh` | `test_probe_rejects_a_repeated_crash_loop_even_inside_the_grace` **red**; reverted, tree clean → the crash-loop guard is not vacuous |
| `pytest` on `test_hermes_liveness`, `test_agent_stack_role`, `test_hermes_config`, `test_lessons_index`, `test_ansible_reads_run_in_check_mode`, `test_shells` | **143 passed** |
| `tests/test_lessons_index.py` (round-5's red test) | **5 passed** — no duplicate lesson numbers: the observability lesson is 759, CI holds 758 |
| `shellcheck -s bash` + `bash -n` + `zsh -n` on `hermes-liveness.sh` | clean |
| `make lint-ansible` | `[SUCCESS] All 26 playbooks parse` |
| `dotf spec digest AI-013-hermes-liveness` vs `review-request.json` | identical for `features.json`, `proposal.md`, `tasks.md`; `spec.md` empty as expected |
| Full suite (`-n auto --dist loadfile`) | **not reproducible green in a bare venv** — 23 failed / 103 errors, each traced to the absent dev toolchain, not to the change: `test_spec_verifications_select_tests.py` failed only because `--no-cov` was unrecognized and passes **23/23** once `pytest-cov` is installed (including all five AI-013 entries, so the contract's verification commands are valid); `test_mutate.py` and `test_host_client_barrier.py` pass in isolation; the one remaining red is `tests/infra/test_network.py::TestDNSResolution::test_local_dns_entries`, a host-DNS check unrelated to this change. The claimed `10676 passed / 96 skipped` therefore stays **UNVERIFIED** by me, not contradicted. |

### Spec and task alignment

- AC1–AC5 map to real behavior tests, not string greps, for the probe: `run_probe` drives the script
  against a fake `docker` binary, so health states, restart counts, start age and daemon failure are
  exercised as behavior. Wiring (timer directives, unit hooks, task ordering) is asserted structurally,
  which is this repo's existing convention for Ansible contracts.
- The round-5 blocker is genuinely fixed and independently confirmed: the lesson-number collision that
  made HEAD red at `8b22f9ec` no longer exists (`test_lessons_index.py` green; only `lesson-759-` in
  observability, `lesson-758-` in ci-automation).
- The round-5/round-4 minors are applied in the tree, not just claimed: `GRACE_SECONDS=90` → `150`
  (`b2b77e24`), `ProtectHome=read-only` + one `ReadWritePaths` socket bind, top-level `.RestartCount`,
  full-path teardown loop (`path: "{{ item }}"`), `rescue` that restores only a timer this run paused and
  then `fail`s, `daemon_reload` gated on changed units, pause predicted from rendered inputs and never
  `enabled: false` (no drift a later run must repair).
- I confirmed the fabric side myself rather than trusting the claim: `kubelab-notify.sh.j2` in
  `--recovered` mode `exit 0`s when the incident count is 0 and when the unit's current `Result` is not
  `success`, so a two-minute successful oneshot does **not** emit a recovery message per run. The
  "recovered … after 1 failed runs" line in `verification.md` is consistent with that code.
- `review-request.json` contract digests match. No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tag exists in any
  of the four contract files.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | archive pre-flight / housekeeping | Three review artifacts inside the spec folder still carry `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` markers: tracked-or-ignored `review-transcript.jsonl` and the **untracked** `review-round4.md` / `review-round5.md` (previous rounds' verdicts, copied in by the launcher). The launcher's own vault-health line names AI-013 as the one active spec with unresolved tags, and `dotf spec archive`'s first pre-flight "refuses to archive while unresolved tags remain" with no `--dry-run` to scope it. If the scan is folder-wide, the archive needs `--force-with-drafts --reason` — a recorded bypass for a check that no contract file actually violates. | `grep -rln 'AGENT-DRAFT\|AGENT-SUGGESTION' specs/AI-013-hermes-liveness/` → `review-transcript.jsonl`, `review-round4.md`, `review-round5.md` only; `git ls-files` shows the round-4/round-5 files are untracked, so deleting them changes no committed state. `dotf spec archive --help` confirms the pre-flight and the permanent `review_bypass:` record. | UNTESTED (scan scope is outside this repository; `dotf spec archive` cannot be dry-run) | none in the contract set — delete the two untracked round files (or move transcripts out of the spec folder) before archiving, or accept the recorded bypass; disposition in `verification.md` |
| Minor | THEORETICAL | provisioning timing | The deploy's health gate allows 24×5 s = **120 s** (`Wait for the Hermes healthcheck to report healthy`) while the probe and the Compose comment declare **150 s** (`60 s start_period + 3×30 s`) as the legitimate startup window. A gateway that becomes healthy between 120 s and 150 s — the window this change explicitly calls normal — fails provisioning, runs the `rescue`, and aborts the deploy. Wrong outcome is a failed provision the operator reruns, not a false page: the probe's own 150 s grace covers the restored timer. | Code read: `tasks/hermes.yml` `retries: 24 / delay: 5` vs `hermes-liveness.sh` `GRACE_SECONDS=150` ("Matches Compose: 60s start_period + three 30s health intervals") and `compose-hermes.yml.j2` `start_period: 60s / retries: 3 / interval: 30s`. Not observed: every recorded provision reached healthy in well under 120 s. | UNTESTED — `test_activation_order_waits_for_gateway_health_before_starting_the_watcher` asserts order and `become`, never the duration | code (`retries`/`delay` to cover 150 s) + tests (a duration assertion); or state 120 s as the deliberate cap in the runbook. Outside the contract set — disposition in `verification.md` |
| Minor | THEORETICAL | detection window (residual) | The 150 s grace only applies while Docker still reports `starting`. Once Docker's own accounting flips the container to `unhealthy` (~`start_period + retries×interval`), the probe pages immediately, whatever `StartedAt` says. So the round-5 fix narrows the earlier 90–150 s false-page window but cannot remove it: the residual boundary is now Compose's definition of unhealthy. The docs are honest about it ("at most 150 s"), and a page at the moment Compose itself calls the gateway unhealthy is defensible — hence a note, not a defect. | `hermes-liveness.sh` lines 28–35 (`status != starting` exits 1 before the age check) vs `compose-hermes.yml.j2` healthcheck block; no live replica of Docker's retry accounting was run. | UNTESTED (needs a live slow start; the fake-Docker fixture supplies the status directly) | code (only if the owner wants grace to outlast `unhealthy`) or runbook wording; disposition in `verification.md` |
| Minor | THEORETICAL | resilience | A paused timer is restored **only** by the block's `rescue`. An interrupted run (SIGINT, lost connection, killed ansible) between `Pause the Hermes liveness timer during gateway recreation` and `Enable the Hermes liveness timer` leaves the watchdog stopped, and nothing reports a stopped detector — silence is indistinguishable from "nothing to report", the exact failure class this spec exists to remove. A rerun heals it (the enable is unconditional on success). | Code read of `tasks/hermes.yml`: pause is `state: stopped` with no `always`/`block`-exit restore; the runbook documents provisioning as the repair path but not the interruption case. | UNTESTED — `test_failed_recreation_restores_a_paused_timer_and_preserves_the_failure` covers the `rescue` path by structure only | code (restore from an `always` block, or record a "paused" marker the next run honours) + tests; runbook note. Outside the contract set |
| Minor | THEORETICAL | test traceability | The disable/unconfigured path and the `rescue` are proven only structurally (task names, ordering, keys) — no live `agent_stack_hermes_enabled: false` provision and no injected deployment failure was performed, and `verification.md` says so. Idempotency and the enabled path were measured live (`changed=0`, `failed=0`), so this is a coverage gap, not a contradicted claim. | `test_unconfigured_hermes_stops_watching_before_taking_the_gateway_down`, `test_failed_recreation_restores_a_paused_timer_and_preserves_the_failure` both assert YAML shape; `verification.md` "Failure restoration is covered structurally, not by a live injected failure". | Named tests exist but assert structure only — no behavioral test | tests (a role-run harness that exercises `rescue`) or an explicitly accepted gap in `verification.md` |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All five ACs have behavioral or live evidence and the negative paths (missing/unhealthy/stopped/crash-loop/invalid-name/daemon-error) are covered; two timing windows (120 s vs 150 s, and grace-outlasts-`starting`) remain. |
| Verification       | B | Inline RED/GREEN, live drill timestamps, `changed=0` and the named commands are all present and the named suite reproduces green here; the full-suite count (`10676/96`) I could not reproduce in a clean worktree, so it stays unverified rather than refuted. |
| Scope              | A | Every spec commit is confined to the watcher script, its two units, the Compose healthcheck, `tasks/hermes.yml`, `tests/test_hermes_liveness.py`, the runbook, lesson 759 and the spec folder; the bulk of the 218-file range is master work merged in. |
| Reliability        | B | Fail-closed probe with validated input, bounded `TimeoutStartSec`, rescue that preserves the original failure, live-measured idempotency; the interrupted-run window leaves the detector stopped silently. |
| Maintainability    | A | 61-line probe, linear control flow with comments explaining *why* (grace arithmetic, the `ProtectHome` boundary), no dead code, no magic constants undocumented. |
| Handoff-readiness  | A | Proposal ACs were updated to the 150 s behavior, runbook and lesson 759 landed with the numbers corrected after the master merges, and `verification.md` carries per-round dispositions instead of a summary claim. |

### Verdict
PASS WITH GAPS

No Blocker and no REAL Major: every finding is either a tracked Minor or a THEORETICAL minor whose cost
is a failed provision or a documented coverage gap. Rubric has no C or D.

### Recommended next steps

Nothing here belongs in the contract set, so this verdict stays fresh for the archive.

- **Before archiving, housekeeping (not a contract edit):** delete the untracked
  `specs/AI-013-hermes-liveness/review-round4.md` and `review-round5.md`, and either remove
  `review-transcript.jsonl` from the spec folder or accept `--force-with-drafts --reason "<why>"`
  with its permanent `review_bypass:` record. Confirm with one archive attempt; if the tag scan is
  contract-file-scoped, no action is needed.
- **Record in `verification.md`** (outside the staleness check) a disposition line for each of the four
  code findings: applied, ticketed, or declined with a reason. The 120 s/150 s mismatch is the one I
  would fix in code (`retries`/`delay`) rather than decline, since the change itself argues 150 s is a
  legitimate startup window.
- **Consider a follow-up ticket** for behavioural coverage of the disable path and the `rescue`
  (currently structure-only), and for the interrupted-run window that leaves the watchdog stopped with
  no signal.
- Do not merge or archive from the implementing session; `proposal.md`/`tasks.md` must not be edited
  after this review or the archive will reject it as stale.
