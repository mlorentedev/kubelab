---
spec: "BACKUP-067-headscale-restore-drill"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "e99481c3ac08551da1f0a07fec4072a003e6b1a2"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-01"
---

## Adversarial review

**Scope**: `BACKUP-067-headscale-restore-drill` — Headscale restore drill (`make backup-drill-headscale`, `toolkit/features/headscale_drill.py`, `tests/test_headscale_drill.py`).
**Sources**: `specs/BACKUP-067-headscale-restore-drill/{proposal,tasks,verification}.md`; `git diff 3aa17579c421465b5bffdae981e9f31d24b3abc8...HEAD` (launcher-resolved base = `3aa17579`, the BACKUP-040 Gitea-drill commit this branch was stacked on). Reviewer drawn from `harness/reviewer-pool.json` by the launcher; not the implementer.

### Reviewed-envelope limitation (disclosed, not a finding against the author)

The base the launcher resolved precedes **five other specs' merges** (BACKUP-046/063/068/070/071), so the 101-file / +6972-line diff also carries `restore_window.py`, `app_drill.py`, `drill_remote.py`, the restic-install extraction, the lesson-index change and the CI kubectl gate. I reviewed the **BACKUP-067 contribution in full** (module, tests, Makefile target, runbook section) plus the shared seams it depends on (`remove_scratch_container`, `drill_remote` stdin path, `conftest` host-client barrier, `pretty_exceptions_show_locals`). I did **not** line-review the other five specs' code; they carry their own archived `review.md` files. Any statement below about "the diff" means the BACKUP-067 path unless it says otherwise.

### What I ran (evidence, in this session)

| Command | Result |
|---|---|
| `poetry run pytest -q --no-cov tests/test_headscale_drill.py` | **40 passed** (rc 0) |
| `poetry run pytest -q --no-cov` on the 13 test files this change touches | **420 passed** (rc 0) |
| `poetry run ruff check` on module, CLI, remote and test file | **All checks passed** (rc 0) |
| `poetry run radon cc -s toolkit/features/headscale_drill.py` | `_restore_and_check` **D (21)**; `parse_entries`/`compare`/`resolve_inputs` C (11) |
| 13 mutation edits, reverted with `git checkout` | 11 killed, **2 survived** (F2, F3) |

I independently reproduced the guards rather than trusting the mutation table: `--network none`→`bridge`, missing-file check disabled, `integrity_check` skipped, key mismatch accepted, empty live list accepted, empty machine key accepted, container removal skipped and `rmtree` no-op **all turn the suite red** (1–16 failures each). That table is substantially honest.

### Spec and task alignment

- **AC1–AC5 are implemented and align with the code.** Missing `db.sqlite`/either key, non-`ok` `integrity_check`, key mismatch, no readable snapshot, live unreadable/empty, unreadable or failed restored lists → all fail or CANNOT CHECK, and all are named.
- **AC4 is the strongest part.** `run_drill`'s outer `finally` removes the container *and* `rmtree`s the workdir unconditionally, then `return ok and removed and wiped` makes a passed restore that left keys or a container behind a **failure**. `remove_scratch_container` verifies removal by reading it back, and `-v` covers the anonymous-volume trap (lesson-498). Mutation: skipping either teardown turns 16 tests red.
- **AC3's negative direction is right.** `read_live` refuses empty *and* unreadable, and `parse_entries` raises on an absent/empty `machine_key`, closing lesson-416's "both sides read `''` and compare equal".
- **Spec-vs-code check**: proposal AC2 says "fails and names the node or user"; `compare()` does name both (`FAIL gcp1 (id 64)`, `FAIL user work`). No mismatch found.
- Task boxes are ticked for implementation; the one open box is `dotf spec review by a different model` (this run). No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in any spec file.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor | REAL | Quality / complexity | `_restore_and_check` is ~105 lines at **CC 21** (radon grade D), and `parse_entries`/`compare`/`resolve_inputs` are at 11. The repo's own law (`AGENTS.md` → Code Quality Rules) is **functions < 40 lines, CC < 10**; the rubric's C band is CC > 15. No CI gate enforces it: `[tool.ruff.lint]` is empty, so `ruff check` cannot see this. | `poetry run radon cc -s toolkit/features/headscale_drill.py` → `F 316:0 _restore_and_check - D (21)`. `ruff check` passes anyway. | Behaviour is covered (40-test file); the *structural* property is **UNTESTED** — nothing asserts a complexity bound. | **code** (bug fix, not contract): extract the restore / start-and-ready / compare phases into three helpers. Behavior-preserving, so `verification.md` can record it. |
| Minor | REAL | Verification honesty / test traceability | `test_the_restored_server_has_no_network_runs_as_the_caller_and_the_image_it_is_given` **names** "runs as the caller" but only asserts `"--user" in start`. `verification.md` cites this test as the evidence for the design decision "the container runs as the invoking user". The value is unguarded. | Mutation `f"{os.getuid()}:{os.getgid()}"` → `"0:0"` left **40/40 green**. | Mutation-surviving. The test itself is the fix site; the property has **no** covering assertion. | **tests** (assert the `--user` value equals `f"{os.getuid()}:{os.getgid()}"`). |
| Minor | THEORETICAL | Correctness (boundary) / test traceability | The snapshot-instant boundary is unguarded: `created == taken` is decided by `created > taken`. Flipping to `>=` changes which entries are excused as "newer than the snapshot" (i.e. skipped by the completeness check) and **no test notices**. Impact is THEORETICAL: `taken` carries sub-second precision from restic while protobuf `created_at.seconds` is whole seconds, so an exact tie is not reachable in practice. | Mutation `if created > taken:` → `>=` left **40/40 green**. | **UNTESTED** — no test pins the boundary. | **tests** (one parametrized case at `created == taken` pinning "excused, not failed"). |
| Minor | SPECULATIVE | Resilience | `ssh()` hardcodes `ConnectTimeout=10` / `BatchMode=yes`; removing them leaves the suite green. Consequence only under an unreachable VPS (a hang instead of CANNOT CHECK). | Mutation removing `ConnectTimeout=10` left **40/40 green**. | **UNTESTED**. | tests (assert the ssh argv), optional — surface only, does not gate. |

Note on the five other specs inside the envelope: not assessed here. Note on `make backup-drill-headscale ENV=dev`: `$(filter staging prod,$(ENV))` silently yields `prod`, so an unrecognised ENV drills prod. I did **not** raise this as a finding because it is the pre-existing convention shared by `backup-coverage`, `-postgres`, `-gitea` and `-apps`, and all these drills are read-only against live (the real restore is manual, in the runbook).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | **A** | Every AC verified on the real prod capture (workstation *and* ace2), negative paths covered, and every guard I mutated went red — no defect observed. |
| Verification | **A** | `verification.md` carries reproducible commands, two prod transcripts and a mutation table; I re-ran the commands and reproduced 11 of 13 mutations independently. |
| Scope | **B** | The BACKUP-067 contribution matches the proposal exactly (module + tests + Makefile + runbook section); the *reviewed envelope* also carries five unrelated specs' merges, disclosed above and not line-reviewed. |
| Reliability | **A** | Teardown is unconditional and read back on every exit path (16 tests red if skipped), no write ever reaches live, and every unreadable input degrades to CANNOT CHECK rather than a pass. |
| Maintainability | **C** | `_restore_and_check` at CC 21 / ~105 lines exceeds the repo's documented CC < 10 and 40-line bar, with no lint gate to catch it. |
| Handoff-readiness | **A** | Spec files current, archive checklist staged, and the "no lesson/ADR/pattern" decision is argued in `verification.md` rather than left silent. |

**Aggregation**: no D; one **C** (Maintainability) → **PASS WITH GAPS** minimum. Severity axis agrees: no Blocker, no REAL Major.

### Verdict

**PASS WITH GAPS**

`dotf spec archive` is **advisable in the current state**: the contract set (`proposal.md`, `tasks.md`, `features.json`) is closed by this review — no edit to it is requested — and the gaps above are Minors, to be dispositioned in `verification.md` or carried into a follow-up ticket. Nothing here blocks the archive. (`dotf spec review` must itself be recorded; the frontmatter above is parsed from this file, `reviewer` spelling matched exactly.)

### Recommended next steps

All of these are **outside the contract set** (`verification.md` is excluded from the staleness check; `proposal.md`/`tasks.md`/`features.json` must not be touched), so they can land after this review without invalidating it:

- **F1 (code)** — split `_restore_and_check` into restore / start-and-ready / compare helpers to bring it under CC 10 and 40 lines. Behavior-preserving; re-run `tests/test_headscale_drill.py` and record it in `verification.md`. Optionally configure `mccabe`/`C901` with `max-complexity` in `[tool.ruff.lint]` so the law in `AGENTS.md` is enforced mechanically instead of by convention — that is the finding's root cause, and it affects the sibling drills too.
- **F2 (tests)** — assert the `--user` value, not merely its presence, so the test earns the name it already has.
- **F3 (tests)** — add one parametrized case at `created == taken` and pin the intended direction.
- **F4 (optional, no gate)** — pin the ssh argv.
- **Disposition each in `verification.md`** (applied / ticketed / declined with a reason). If F1 is deferred, file it as a bitácora ticket naming `_restore_and_check` and the sibling drills sharing the shape, since a verbal deferral is not an exit.
