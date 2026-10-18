---
tags: [spec, verification, templates]
created: "2026-08-11"
---

# Verification - OPS-016-dnat-drift-healing

## Evidence

| AC | Status | Proof |
|----|--------|-------|
| AC1, an unchanged seed keeps every id and deletes nothing | Met | #992 (`db436d32`), a keyed upsert diff in `toolkit/features/monitoring_diff.py`. `tests/test_monitoring_diff.py::TestDiffIsNonDestructiveOnASteadyState` and `tests/test_monitoring_integration.py::test_second_apply_is_a_no_op_and_preserves_every_id`, the latter against a real Uptime Kuma container (#999, `f30711e0`). Live, 2026-10-18: `make monitoring-apply CHECK=1` reported `Sync plan: 0 create, 0 edit, 0 delete (live=36, seed=36)` against rpi3 |
| AC2, add, edit and remove converge in one apply | Met | `test_dropping_a_monitor_from_the_seed_deletes_exactly_that_one` and `test_renaming_a_monitor_edits_it_instead_of_recreating_it` (integration), plus `TestDiffMatching` (unit) |
| AC3, no fixed sleep, and an unmet precondition fails | Met; delete branch untested (#2506) | The `time.sleep(3)` is replaced by a bounded poll over authoritative reads that raises (`monitoring.py`, the wait helper above `apply_monitors`). `tests/test_monitoring_apply_gate.py::test_a_monitor_that_fails_to_converge_fails_the_apply`. The remaining `time.sleep` calls are the bootstrap socket settle and the poll interval, not a guess at a precondition |
| AC4, an agent-port monitor for every node | Not met, carried | No agent monitor in `infra/config/uptime-kuma/monitors.json`. Owned by #963, which waits on #2450 (does Glances survive the Homepage retirement) |
| AC5, DNAT drift is restored | Amended, partial | #1115 (`b27321cc`) found the trigger and fixed it per role. `glances` and `agent_stack` compare `HostConfig.PortBindings` against `NetworkSettings.Ports` and recreate on divergence, and the boot units start after the Tailscale address exists. `rpi3_services` lacks the recreate and the check: #2500. **Not run for this archive:** no off-node probe and no `changed=0` re-run on `glances`/`agent_stack`, and no test drives their drift branch. The amended claim rests on the code, `tests/test_tailscale_bound_ports_survive_boot.py` (ordering) and `tests/test_beelink_compose_unit.py` (Beelink's recreate) |
| AC6, headscale is never recreated | Superseded | The fleet sweep it guarded was never built. Each per-role recreate names only its own project, and the `headscale` role has none |

## Test status

- `poetry run pytest tests/test_monitoring_diff.py tests/test_monitoring_apply_gate.py tests/test_monitoring_bootstrap.py --no-cov -q`: 63 passed (2026-10-18). The integration file needs Docker and runs under `make test`.
- No regressions: this archive changes only the spec folder.

## Decisions made during implementation

- Treat the trigger, not the symptom. The spec deliberately planned a fleet-wide DNAT sweep because
  the cause would not reproduce. Five days later #1115 measured it, a tailscaled boot race, and the
  per-role fix made the sweep unnecessary. The sweep was never built, which also made AC6 moot.
- AC4 is held for #2450 rather than built: a monitor for an agent that may be retired is work that
  gets deleted.

## Review dispositions

First review, `53d1aa31`, **FAIL**:

1. Major, no `features.json` although `tasks.md` commits to one: applied. Added with one entry per
   AC; AC4 to AC6 carry their tickets instead of `passing`. The guard's blindness to a missing file
   is added to #2501.
2. Major, the delete-convergence `raise` can be removed with the suite green: ticketed as #2506,
   because tests are outside this archive's write scope. The same ticket covers `except Exception`
   counting any read error as deleted.
3. AC5's narrowed wording has no run behind it: applied. The row now says what was not run.
4. Closing boxes unticked: applied, with a disposition in `tasks.md`.
5. The delete-path risk had two states across contract files: applied, and `proposal.md` now marks it
   resolved by #999.
6. AC6 "met by construction" read as satisfied: applied, reworded to superseded.

Second review, `0690f54a`, **PASS WITH GAPS**:

1. Major (THEORETICAL), the delete-convergence `raise` still has no test that fails without it:
   ticketed, #2506, as in round 1. Tests stay outside this archive's write scope.
2. Minor, `features.json` states set to `passing` by the implementer rather than a harness run:
   applied as a record. The implementer set f1 to f3 by hand in `0690f54a`, after running each
   entry's `verification` command to exit 0. No harness run exists, because `dotf spec` has no
   verify subcommand. The reviewer re-ran all three commands to exit 0. The missing provenance
   check belongs with the guard gaps in #2501.
3. Minor, the live `CHECK=1` claim behind AC1 had no transcript: applied. It was re-run against
   rpi3 on 2026-10-18: `make monitoring-apply CHECK=1` printed `Sync plan: 0 create, 0 edit,
   0 delete (live=36, seed=36)` and `CHECK: nothing written`. The Docker-gated integration tests
   (#999) were not re-run and stay UNVERIFIED for this archive.
4. Minor, the Closing boxes are uniformly unticked: declined. `tasks.md` is in the contract set,
   and its note already explains each box. Type checks and lint were not re-run because the
   archive changes no code.
5. Question, who set `passing`: answered in item 2.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? no: #1115 and the boot-unit comments in `beelink_services` and `rpi3_services` already record the boot race; #2500 carries the one gap
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the change of approach is recorded in the amended criteria
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: one project

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OPS-016-dnat-drift-healing/` -> `specs/archive/OPS-016-dnat-drift-healing/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
