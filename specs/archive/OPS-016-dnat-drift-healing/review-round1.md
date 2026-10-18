---
spec: "OPS-016-dnat-drift-healing"
verdict: "FAIL"
reviewed_sha: "53d1aa31232150d87f9b011fd91f49e38f6a8a3a"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: `OPS-016-dnat-drift-healing` — the amendment commit that closes the spec (`53d1aa31`, 3 spec files) plus the spec's substantive work as it exists in `HEAD` (monitoring sync in `toolkit/features/monitoring.py` + `monitoring_diff.py`, per-role Tailscale port healing in `infra/ansible/roles/{glances,agent_stack}/`).

**Sources**: `specs/OPS-016-dnat-drift-healing/{proposal,tasks,verification}.md`; `git diff 68b35a573c4709a61c5a60b142065540c9db3923...HEAD`; `git show 53d1aa31`; `toolkit/features/monitoring.py`; `tests/test_monitoring_diff.py`; `tests/test_monitoring_apply_gate.py`; `tests/test_monitoring_bootstrap.py`; `tests/test_monitoring_integration.py`; `tests/test_tailscale_bound_ports_survive_boot.py`; `infra/ansible/roles/glances/{tasks/main.yml,templates/kubelab-glances.service.j2}`; `infra/ansible/roles/agent_stack/tasks/{main,hermes}.yml`; `infra/ansible/roles/headscale/tasks/main.yml`; `tests/test_spec_verifications_select_tests.py`.

**Diff-scope note.** The launcher's base (`68b35a57`, 2026-08-10) predates ten weeks of unrelated master history, so `base...HEAD` measures **2028 files / +201 674** — nearly all of it work that landed through other PRs and other specs. The change actually authored here is `53d1aa31` alone: `proposal.md` (12 lines), `tasks.md` (40), `verification.md` (33), no code. I treated the diff as that commit, and checked its claims against the code and tests it cites rather than against the 201k-line surface.

### Spec and task alignment

- **AC1 / AC2 / AC3 — met, and the named tests exist and pass.** I ran `poetry run pytest tests/test_monitoring_diff.py tests/test_monitoring_apply_gate.py tests/test_monitoring_bootstrap.py --no-cov -q` → **63 passed in 6.46s**. `TestDiffIsNonDestructiveOnASteadyState`, `TestDiffMatching`, `test_a_monitor_that_fails_to_converge_fails_the_apply` all exist where `verification.md` says. The delete-all/recreate body is genuinely gone, the diff is a pure keyed function in `monitoring_diff.py`, and the fixed `time.sleep(3)` is replaced by a bounded poll over `get_monitor(id)` (`monitoring.py:267-295`). The two surviving `sleep(0.5)` calls are a poll interval and a socket settle, not a guessed precondition — the AC3 wording ("no fixed `sleep`") is satisfied in substance.
- **AC4 — honestly unmet.** No agent-port monitor exists in `infra/config/uptime-kuma/monitors.json`; #963 is **OPEN**, blocked on #2450 (**OPEN**, "Glances has no consumer since Homepage was retired"). The amendment says exactly this. Nothing is claimed that is not true.
- **AC5 — the narrowed claim is true in code.** `glances/tasks/main.yml:106-118` reads `HostConfig.PortBindings` against `NetworkSettings.Ports`, and `:165-170` adds `--force-recreate` when `_glances_port_drift`; `agent_stack` carries the same inspect format at `tasks/main.yml:263` and `tasks/hermes.yml:432`. The boot unit (`kubelab-glances.service.j2`) documents the race, orders `After=tailscaled.service` and runs `wait-for-tailscale-addr.sh` before `up -d --force-recreate`. Fleet guard: `tests/test_tailscale_bound_ports_survive_boot.py` → **7 passed**. `rpi3_services` has no recreate and no binding check; #2500 is **OPEN** with precisely that title. #1115 is merged.
- **AC6 — reclassified, not satisfied.** "Met by construction, not by a test" is accurate as an outcome (`grep` finds no `force-recreate` in `infra/ansible/roles/headscale/`), but the criterion as written asked for a *test*; what happened is that the artifact the test would guard was never built. The disclosure is explicit, so this is a question of record-keeping, not of honesty.
- **`tasks.md` evidence vs `proposal.md` risks.** `tasks.md` Setup says the delete path was "exercised by `tests/test_monitoring_integration.py::test_dropping_a_monitor_from_the_seed_deletes_exactly_that_one`", while `proposal.md` still lists "**OPEN — the delete path was never exercised**". Both are defensible about different propositions (the *probe* never covered deletes; the *integration test* now does), but two contract files describe one fact in two states.
- **`tasks.md` Closing is entirely unticked** — including `verification.md filled in`, which *is* filled, and `Type checks pass` / `Lint passes`, which I did not run (see UNVERIFIED below).
- **`features.json` — declared, required by the same file, absent.** `tasks.md` §"Machine-readable features" states "This spec emits a sibling `features.json`", and Closing requires "Every acceptance criterion … has a matching entry in `features.json`". There is no such file. The launcher's own `review-request.json` records `"features.json": ""`.
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` tags remain anywhere in the spec folder.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | spec contract | `features.json` is absent while `tasks.md` — a contract file — declares the spec emits it and makes AC coverage conditional on it. Every AC of this spec is therefore outside the machine gate the spec itself specifies. | `ls specs/OPS-016-dnat-drift-healing/` shows only `proposal/tasks/verification/review-request/review-transcript`; `find specs -name features.json` has no entry for this folder; `review-request.json` sets `"features.json": ""`. `tests/test_spec_verifications_select_tests.py:81` globs `*/features.json`, so **absence is silently tolerated** — the guard that exists cannot notice a spec with no features at all. | UNTESTED — no test asserts an active spec carries `features.json`; the file's own "floor" test (`test_active_specs_carry_pytest_verifications`) is satisfied by the other specs' files. | spec (`features.json`) + tests (a floor that counts active specs) |
| Major | THEORETICAL | resilience | The delete-convergence guard — the one that stops #925's duplicate-monitor failure — has no test that makes it fire. Its `raise` can be deleted with the suite still green. | Mutation: replaced the `if pending: raise RuntimeError(...)` block at `monitoring.py:293-296` with `logger.success("...")`; re-ran the three files → **63 passed**, identical to the unmutated run. Reverted (`git status` clean). `test_dropping_a_monitor_from_the_seed_deletes_exactly_that_one` proves convergence *when the delete completes* (set equality + count), never non-convergence. `proposal.md` demands exactly this test ("AC3's bounded poll must therefore be written against a real delete … before it is asserted to work"). | UNTESTED — the named delete test never induces a non-converging delete. | tests |
| Minor | REAL | verification.md | AC5's recorded proof was rewritten to the narrowed claim but no run backs the new wording: "probed over HTTP from off-node" and "re-run on the now-healthy node reports `changed=0`" have no transcript, and no per-node `changed=0` is recorded for `glances`/`agent_stack`. What exists is the code plus a static role guard. | `verification.md` AC5 row; `tests/test_tailscale_bound_ports_survive_boot.py` asserts unit ordering only, never the `_glances_port_drift` → `--force-recreate` branch. | `test_a_tailscale_bound_port_is_ordered_after_the_address_exists` (7 passed) — covers ordering, **not** the drift-repair branch | verification.md (evidence) + tests (drift branch) |
| Minor | REAL | record-keeping | `tasks.md` Closing is all `[ ]`, one of them demonstrably true (`verification.md filled in`) and two never run in this change (`Type checks pass`, `Lint passes`). A reader cannot tell "not done" from "done, unticked". | `tasks.md` §Closing; `verification.md` is filled (45 lines, per-AC table). | UNTESTED (bookkeeping) | verification.md |
| Minor | REAL | contract consistency | One fact, two states across contract files: `proposal.md` keeps "OPEN — the delete path was never exercised", `tasks.md` Setup marks it exercised by `#999`. | `proposal.md` Risks bullet *OPEN*; `tasks.md` Setup 4th box (`✓ 2026-08-11: exercised by …test_dropping_a_monitor…`). | UNTESTED (record) | spec (contract set — folded into the re-review this FAIL already requires) |
| Question | — | AC6 record | AC6 is recorded as "met by construction", but the criterion asked for a *test* that the drift task never recreates headscale. What actually happened is that no such task exists. Confirm the archive should say **superseded**, not **met** — "met by construction" reads as a satisfied criterion to anyone skimming the table. | `proposal.md` AC6 amendment; `grep -rn 'force-recreate' infra/ansible/roles/headscale/` → no match. | UNTESTED — nothing can test a task that was never built | spec (wording only) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | AC1–AC3 verified green by me; AC4–AC6 unmet (openly carried to #963/#2450/#2500); the delete-divergence guard is not covered by any test that can fail it. |
| Verification       | B | Named tests exist, run and pass (63 + 7); the live rpi3 `CHECK=1` claim is not reproducible from this worktree and no per-id before/after was recorded — the spec says so itself. |
| Scope              | A | The authored commit is 3 spec files, nothing else; no unrelated change. |
| Reliability        | B | Bounded poll raises instead of logging SUCCESS; per-role recreate; the one known gap (`rpi3_services`) is ticketed as #2500. |
| Maintainability    | A | Diff logic extracted into a pure `monitoring_diff.py`; comments explain *why*; 63 unit tests around the apply path. |
| Handoff-readiness  | C | Unmet ACs carry ticket ids (exemplary), but `features.json` — the spec's own machine-readable handoff — is missing, and the Closing section is uniformly unticked. |

### Verdict
FAIL

Two things are true at once here, and the severity × reality rule resolves them separately. The *substance* of this spec is in good shape: AC1–AC3 are met and their tests pass under my own run, AC4/AC5/AC6 are openly unmet with live tickets (#963 → #2450, #2500, #1115 merged), and the amendment commit is scoped to three files. The failure is in the contract, not in the code: `features.json` is missing although `tasks.md` — one of the three files whose digest the archive gate watches — commits to it, and the repo's only guard against that is structurally blind to a spec with no features file. A REAL Major in the contract set forces FAIL, and it also means the fix cannot be a passing-verdict footnote: adding the file invalidates the review, so the next round is the mechanism.

### Recommended next steps

**Contract set (required before re-review — this is why the verdict is FAIL):**
- `specs/OPS-016-dnat-drift-healing/features.json` — one entry per AC with `id`, `behavior`, `verification` (the named commands, e.g. `poetry run pytest tests/test_monitoring_diff.py -q`), `state` and `evidence`. For AC4/AC5/AC6 the honest `state` is the carrier ticket, not `passing`; the spec's own text forbids the agent from writing `passing`, so leave those to the harness.
- `tasks.md` Setup box 4 and the `proposal.md` "OPEN — the delete path was never exercised" bullet describe one fact in two states; align them while the contract set is open anyway (Minor, but it is free in this round).
- Then `dotf spec review OPS-016-dnat-drift-healing` again — the archive gate will reject this review as stale the moment the contract changes, by design.

**Outside the contract set (disposition in `verification.md` as applied / ticketed / declined):**
- Add a test that makes the delete-divergence guard fail when removed (`monitoring.py:293`). The mutation I ran is the proof it is currently unguarded; a Docker-gated integration case that deliberately withholds the delete's convergence (or a unit case that stubs `get_monitor` to keep returning the deleted monitor past the deadline) closes it. Also useful: fold the missing-`features.json` case into `tests/test_spec_verifications_select_tests.py` so the next spec cannot skip the gate silently.
- Record AC5's real evidence, or state plainly that the narrowed criterion rests on code plus the static role guard. A `changed=0` re-run on `glances` and `agent_stack` would close it; so would saying it was not run.
- Consider rewording AC6 from "met by construction, not by a test" to "superseded", so a skim does not read a withdrawn criterion as a satisfied one.
- **UNVERIFIED in this run**: `make type` and `make lint` (the unticked Closing boxes). I ran the three named pytest files and the role guard; I did not run the full suite, the linters, or the Docker-gated integration file (`make test`), and I left the tree clean apart from this review.
