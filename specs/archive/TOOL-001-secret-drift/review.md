---
spec: "TOOL-001-secret-drift"
verdict: "PASS"
reviewed_sha: "d1131364f807e47174bbd34b9eceb0ed80b1a468"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: TOOL-001-secret-drift — archive of a never-implemented spec as *integrated*
**Sources**: `specs/TOOL-001-secret-drift/{proposal,tasks,verification}.md`, `review-request.json`;
commit `d1131364`; `toolkit/cli/secrets.py`, `toolkit/features/{configuration,secrets_manager}.py`,
`toolkit/cli/../Makefile`, `CLAUDE.md`; live issue state for #2499 / #520 / #521 / #584 / #2443.

### Scope note (stated, not assumed)

The launcher's `base_sha` (`d9108383…`) is **1128 commits behind HEAD**, so
`git diff d9108383…HEAD` is the whole repository's evolution (2356 files, +247k), not this
spec's work. The actual branch delta is one commit: `origin/master..HEAD` = `d1131364`,
touching `CLAUDE.md` (1 line) and `verification.md` (55 lines). I reviewed that commit and
validated every claim it makes against the working tree, rather than reading a 247k-line diff
as if it were the change. This is recorded because the stated base would otherwise let a review
report on a diff that is not the change under review.

### Spec and task alignment

- `tasks.md` has **every box unticked** — and that is honest, not a discrepancy: nothing was
  built. There is no `toolkit secrets diff` anywhere in `toolkit/cli/secrets.py`, so the spec's
  implementation tasks are legitimately unfulfilled and the archive says so rather than
  back-filling them.
- `proposal.md` keeps its acceptance criteria unticked, including the three the archive admits
  were never met. `status:` is still `draft` and the folder is still active — correct at this
  point, because `dotf spec archive` is what rewrites the status and moves the folder.
- The archive's substance is its **per-AC evidence table**, and each row survived checking:
  - AC1 (exit 0 when envs agree): audit exits 1 only on new orphans or malformed values
    (`toolkit/cli/secrets.py`, the ratchet block at the end of `audit`). True.
  - AC2 (staging-only key, exit 1) marked **Partial**: confirmed — a *catalogued* key missing
    from an env is printed under `Missing` and the command still exits 0. `#2499` is OPEN with
    exactly that title. True, and the gap is not hidden.
  - AC3 (never print a value): `tests/test_secrets_value_shape.py::test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key`
    asserts `GENERATED not in outcome.output` at the CLI boundary; `TestItCannotLeakValues`
    covers the key-path walk. True — and stronger than the row claims (see Minor 4).
  - AC4 (decryption failure → exit 2) marked **Not met**: confirmed by reading
    `ConfigurationManager._decrypt_sops` (`toolkit/features/configuration.py:86-105`), which logs
    and returns `{}` on `CalledProcessError`, so the audit sees an empty vault. `#2499` carries it.
  - AC5 (`--format json`) marked **Not met**, carried in `#2499`.
  - AC6 (shape mismatch → exit 1) marked **Integrated, stronger**: confirmed —
    `secrets_manager.py:2070` applies `re.fullmatch(spec.value_pattern, …)` and `malformed`
    raises `Exit(1)`.
- **The supersession argument itself holds**: a catalog-driven audit does catch a key missing
  from *both* envs, which a pairwise compare cannot. TOOL-013 (`#584`) remains the open home for
  the cross-env compare the proposal described, and TOOL-002 (`#521`) is still open on its own.
- The archive gate's own parser was checked rather than assumed: `dotf spec archive` requires the
  `## Promotion candidates` lines to answer `yes:`/`no:`, and
  `judgePromotion` (`cli/internal/spec/promotion.go`) strips the literal prefix
  `Only if this recurs in >1 project.`, which is why line 49 here parses. All three lines answer
  `no:` with a reason. This change will not be refused by the promotion pre-flight.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | handoff / evidence | `verification.md` states "Archived 2026-10-18" in the past tense while the archive has not run: `proposal.md` is still `status: draft`, the folder is still active, and all three checklist items are unchecked. An assertion ahead of its own evidence; if the archive is blocked, the file is false as written. | `git show d1131364 --stat`; `head -8 proposal.md`; `## Archive checklist` all `[ ]` | UNTESTED | `verification.md` (outside the contract set) |
| Minor | REAL | board / DoD | The archive leaves `#520` (the spec's own `issue:` per proposal frontmatter) **OPEN**. `dotf spec archive` is documented as "Mechanical only" — it rewrites status and moves the folder, and closes nothing. Nothing (test or gate) enforces "archived spec ⇒ tracking issue closed", so the board keeps an open item whose spec no longer sits under `specs/`. | `dotf spec archive --help`; `gh issue view 520` → OPEN; checklist item 3 `[ ]` | UNTESTED (the existing spec gate runs the opposite direction: closed issue + active spec) | tooling (`dotf`/`spec_gate`) + issue state |
| Minor | REAL | knowledge hygiene | The CLAUDE.md gotcha was corrected, but the two older artifacts that created TOOL-001 still present it as live backlog: `docs/lessons/identity-secrets/lesson-163-…md:17,19` ("Created backlog items TOOL-001 … Automate this with TOOL-001/TOOL-002") and `docs/audits/process-audit-2026-07-07.md:119,466`. A reader following the lesson is sent to an archived spec. | `grep -rn TOOL-001 CLAUDE.md docs/` | UNTESTED (no test resolves prose spec-ID references) | repo `docs/` (outside the contract set) |
| Minor | REAL | verification traceability | AC4's fact ("an undecryptable vault reads as every key missing and exits 0") has **no named test**: the closest, `test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key`, patches `_decrypt_sops` away. I confirmed the behaviour by code reading only; the row should say so, or `#2499` should add the test. | `toolkit/features/configuration.py:86-105`; `tests/test_secrets_value_shape.py:73` | UNTESTED | tests (lands with `#2499`) |
| Minor | REAL | verification accuracy | AC3 is *under*-cited: the strongest proof is the CLI-boundary assertion that the generated value never reaches `outcome.output`, yet the row cites only the `orphan_key_paths` unit test. Understating coverage on the security-critical criterion invites a later reviewer to re-litigate it. | `tests/test_secrets_value_shape.py::test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key` (passes) | that test (named) | `verification.md` (outside the contract set) |
| Question / assumption | REAL | wording vs behaviour | "The need it named … is covered by a different design" is true for **reporting** (the missing key is named against the lacking env) and false for **gating** (exit 0). The AC table discloses it and `#2499` is open, so this is disclosed, not concealed — but the headline word "integrated" is what a skimming reader keeps. Recommend the section state the gate gap in its first paragraph, not only in row 2. | exit-code path in `toolkit/cli/secrets.py`; `#2499` OPEN | n/a | `verification.md` (outside the contract set) |

Surface-only, no action: this spec has no `features.json` (never did, since 2026-05-13), so
`tests/test_spec_verifications_select_tests.py` — which globs `specs/*/features.json` — imposes no
selector check on it. Adding one now would edit the contract set and stale this review; declining.

### Evidence actually run (not asserted)

- `uv run … pytest tests/test_orphan_secrets_ratchet.py tests/test_secrets_orphan_audit.py -q` →
  **14 passed**. `tests/test_secrets_value_shape.py` → **10 passed** (includes the no-value and
  exit-1 assertions). Both named tests in the verification table exist and pass.
- `gh issue view` → `#2499 OPEN` ("secrets audit exits 0 when a catalogued secret is missing or a
  vault fails to decrypt"), `#520 OPEN`, `#521 OPEN`, `#584 OPEN`, `#2443 OPEN` (the WIP-limit
  sweep that motivates archiving). Every issue reference in the change resolves.
- `grep "\"diff\"\|'diff'" toolkit/cli/secrets.py` → no matches: `toolkit secrets diff` does not
  exist, as stated.
- Working tree left clean apart from this `review.md` and the launcher's `review-request.json`.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Every factual claim checked holds (code paths, tests, open issues); two labels are less precise than the evidence — "Archived" written before archiving, "integrated" headlining a report-only replacement. |
| Verification       | B | Reproducible: I re-ran the named tests and re-read the code paths myself; AC4 rests on code reading with no named test, which the change does admit. |
| Scope              | A | Two files: one CLAUDE.md gotcha line plus the 55-line per-AC evidence table. No creep, no back-filled tasks. |
| Reliability        | A | Docs-only; the promotion-candidate lines parse against `judgePromotion`, so the archive pre-flight will not refuse them, and no link or path is introduced that does not exist. |
| Maintainability    | A | Table-per-criterion with status and destination, reasons in prose, short sections; a future reader can see what was and was not delivered. |
| Handoff-readiness  | B | Spec-side handoff is genuinely good (three promotion answers with reasons); the transition leaves `#520` open with a manual step nothing enforces, and two docs still call TOOL-001 live backlog. |

### Verdict
PASS

No blocker and no REAL Major. The archive's central claim — that the need is served by a
different, existing design while three criteria remain unmet and tracked — survived every attempt
I made to break it: the code paths it cites behave as described, the tests it names exist and
pass, and each carrying issue is open with the matching subject. The minors concern how the
transition is finished (stale pointers, an open tracking issue, evidence cited less sharply than
it could be), not whether the decision to archive is sound.

### Recommended next steps

Every item below is **outside the contract set** (`proposal.md`, `tasks.md`, `features.json`), so
none of them stales this verdict. Disposition each in `verification.md` — applied, ticketed, or
declined with a reason.

- On running `dotf spec archive TOOL-001-secret-drift`: rewrite the "Archived 2026-10-18" tense to
  match, tick the three checklist items, and **close `#520`** pointing at `#2499` and `#584`
  (Minor 1, 2).
- Correct the two stale references in `docs/lessons/identity-secrets/lesson-163-…md` and
  `docs/audits/process-audit-2026-07-07.md` so TOOL-001 reads as archived/superseded (Minor 3).
- When `#2499` lands the decrypt-failure path, add the named test for "undecryptable vault ⇒
  every key missing" and fix the exit code; that also closes the AC4 evidence gap (Minor 4).
- Optionally cite `test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key` in the AC3 row
  (Minor 5), and lead the "Integrated" section with the gate-not-reporting caveat (Question).
