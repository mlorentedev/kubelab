---
spec: "CONSOLE-002-cross-context-bitacora"
verdict: "FAIL"
reviewed_sha: "fbb35c75fe6a298051c6fe7b726cae966151103d"
reviewer: "nan/qwen3.8-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: CONSOLE-002-cross-context-bitacora (abandonment as superseded; kubelab#2443 → #2494 carry)
**Sources**: `specs/CONSOLE-002-cross-context-bitacora/{proposal,tasks,verification,features}.md`;
stated base `6a69a8b9c199ff045a3e71778744f228b470b556...fbb35c75`; ADR-050 / ADR-051 / ADR-066;
`.github/workflows/{ci.yml,ci-pipeline.yml}`; `apps/api/src`; `infra/config/values/common.yaml`;
`infra/k8s/base/services/{postgres.yaml,vikunja.yaml,vikunja-config/vikunja.env}`; issues #2443, #2494.

**Attribution note.** The stated base is the direct parent of the spec's first commit (`git rev-list
--count 6a69a8b9..472dc776` = 1), but the spec's four commits landed on `master` through four
months and separate squash-merges, so `git diff base...HEAD` spans **1028 commits / 2213 files /
+216,027 lines**, almost none of it this spec. I reviewed the spec-attributable commits
(`472dc776` PR-0 harness, `c1db49e1` PR-1a Postgres, `d7d58861` ADR-050 D5 amendment, `fbb35c75`
the supersession record at HEAD) plus the artifact set those commits leave behind. I did **not**
audit the other ~1024 unrelated commits; that is not what this spec's archive gate is for.

**What HEAD actually changes** (`git show --stat fbb35c75`): 2 files, +25/−3 — an ADR-050 status note
and a `## Abandoned` section in `verification.md`. Docs only; no code, no test deletion, no secret,
no injection surface.

### Spec and task alignment

- The **substantive claims in the change are all true, and I reproduced them rather than trusting
  them**:
  - PR-0 "the Go test harness, `go test -race ./...` in CI" — `ci-pipeline.yml:116-119`
    (`name: Test API code`, `run: go test -race ./...`, `working-directory: ./apps/api/src`), reached
    from `ci.yml:237-243` (`api-pipeline` → `with: app: api`), so the condition is satisfiable and the
    step sits before `Build API binary`. Locally: `go vet ./...` clean; `go test -race ./...` → `ok
    internal/health 1.212s`, `ok pkg/config 1.130s`, 0 failures.
  - PR-1a "Postgres on K3s, `infra.postgres` SSOT, ADR-051" — `infra/k8s/base/services/postgres.yaml`
    exists, `infra/config/values/common.yaml:421` `postgres:` block, `toolkit/features/secrets_manager.py:1698`
    `key_path="infra.postgres.password"`, `docs/adr/adr-051-postgres-data-service.md` exists.
  - "Vikunja now runs on it" — `vikunja-config/vikunja.env:28-32`: `VIKUNJA_DATABASE_TYPE=postgres`,
    `VIKUNJA_DATABASE_HOST=postgres`, db `vikunja`; `vikunja.yaml:27-29` a `wait-for-postgres` init
    container; ADR-066 lines 31/44 say the same. (Live cluster state: UNVERIFIED from a worktree.)
  - ADR-066 supersession — `status: accepted`, `date: "2026-08-27"`, Status line: "amends and
    supersedes the custom Go API console build decision of ADR-050 (D1)", and line 37 carries the
    quoted reason "**heavy maintenance debt**". The quote in the new status note is accurate.
  - "#2494 carries AC4" — `gh issue view 2494`: OPEN, "Per-context LLM egress policy, default-deny
    (ADR-050 D5) has no implementation", body restates AC4 with the **correct** post-amendment default
    ("resolves to **no provider**") and names CONSOLE-002 AC4 as its source. #2443 exists and is OPEN.
  - The `"D1-D4, D6 and D7 are unaffected"` quotation in the ADR-050 note matches ADR-050 line 35
    verbatim, and the note's disambiguation ("unaffected *by that amendment*, not in force") is a
    genuine correction of a real misreading.
- **No `[AGENT-DRAFT]` blocker.** `proposal.md:13` mentions the tag, but backtick-wrapped;
  `ScanUnresolvedTags` runs each line through `stripCodeSpans` (`dotfiles cli/internal/spec/archive.go:118`),
  so the archive's first pre-flight will not false-positive on it. Checked against the gate code,
  not assumed.
- The `## Evidence` AC table is left as the unfilled template with `[ ]` on all four criteria, and
  `features.json` keeps all four at `"state": "pending"`, `"evidence": ""`. That is the **honest**
  representation of an abandoned spec: nobody is claiming AC1–AC3. No `dotf spec archive` gate reads
  `features.json` (no features check in `archive.go`), so nothing there blocks the move either.
- **Where the record is not internally consistent is the finding set below**: two of the three
  contract files disagree with the third, in ways that outlive this PR because the folder is about to
  become a permanent audit trail.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| **Major** | **REAL** | spec / security-control SSOT | `features.json` f4 still states the abandoned default: *"A Context with no explicit provider policy resolves to **local-only (Ollama)**"*. ADR-050 as amended 2026-10-01 makes it **no provider / refused**, and the amendment's own text calls the other reading the thing that "silently turns a security control into a cloud default". `proposal.md` AC4 was fixed; the machine-readable twin was not — so one spec now carries two opposite answers to the AC that #2494 is going to implement. | `features.json` f4 vs `proposal.md` AC4 vs `adr-050…md:27-30`; `git log --oneline -- …/features.json` → **one** commit (`472dc776`); `d7d58861 --stat` touched `adr-050` + `proposal.md` only. That PR's own body claims the spec "carried the Ollama default in three places … All three now say 'no provider'" — `features.json` was the fourth and still says Ollama. | **UNTESTED** — `tests/test_spec_verifications_select_tests.py::test_every_verification_selects_a_test` keys on the `_PYTEST` regex (`poetry run pytest`, line 43) and so inspects neither behaviour text nor `go test` selectors; no test compares `features.json` behaviour to the ADR. | **spec — contract set (`features.json`)** → fix, then re-review |
| **Major** | **REAL** | spec / handoff hygiene | `tasks.md` still reads as **live work**: heading "PR-0 — `go test` CI step + first Go test harness **← IN FLIGHT**", "**PR-1b** — atlas schema + Go data layer **(next)**", four unticked boxes under PR-0/PR-1a, and the whole "Closing (whole module)" checklist unticked. The supersession is recorded only in `verification.md`. Archived as-is, the folder hands a future reader a plan with a next step that was rejected two months ago by ADR-066. | `tasks.md` as of HEAD (quoted headings/boxes) vs `verification.md` `## Abandoned`; `git show --stat fbb35c75` → `tasks.md` untouched. Worse, one unticked closing box — "Every acceptance criterion has a `features.json` entry with a **non-vacuous** verification command" — is now demonstrably unmet (next row), so the box is not merely unchecked, it is unchecked-and-uncheckable. | **UNTESTED** — no test asserts a spec's `tasks.md` matches the state its `verification.md` records. | **spec — contract set (`tasks.md`)** → fix, then re-review |
| Minor | REAL | tests / verification integrity | Every `features.json` verification command targets a package that does not exist: `./internal/board/...` and `./internal/board/forge/...`. `ls apps/api/src/internal` → `api constants health models services` — no `board`. The commands can never have selected a test, and the repo's own vacuity guard cannot see it because it only parses pytest selectors. | `features.json` f1–f4 `verification` strings; `ls apps/api/src/internal`; `_PYTEST` regex at `tests/test_spec_verifications_select_tests.py:43` (pytest-only). For an abandoned spec the practical cost is the trap, not the run: a reader who copies f4's `TestResolveContextPolicyDefaultDeny` into #2494 inherits a name with no referent. | `tests/test_spec_verifications_select_tests.py::test_every_verification_selects_a_test` — covers pytest only; a `go test -race ./pkg/... -run TestX` selector is **outside** its reach (that blind spot is the ticketable part). | code/tests (follow-up: widen the guard to `go test` selectors) + spec |
| Minor | REAL | docs accuracy | `verification.md`'s "Archive checklist" points at the wrong destination for the route this change chose: it says move to `specs/archive/CONSOLE-002-…/` and set `status: archived`, while the supersession is being recorded as **abandoned** — `dotf spec archive --abandoned` writes `status: abandoned` and moves to `specs/archive/_abandoned/<id>/` (that directory exists in this repo; `specs/archive/_abandoned/`), which is also where #2443's WIP-limit disposition lands it. | `dotf spec archive --help` ("or `specs/archive/_abandoned/` under `--abandoned` … rewrite the proposal status to archived/abandoned"); `ls -d specs/archive/_abandoned` present, `specs/_abandoned` absent; `verification.md` Archive checklist lines. | UNTESTED (doc-only) | **outside the contract set** — `verification.md` is not watched by the staleness check; fix it in the same commit as the two above without invalidating the next review |
| Minor | THEORETICAL | process / review mechanics | The launcher's base resolution hands a reviewer a 1028-commit window for a 2-file change, and nothing in the request lets the reviewer tell "this spec's work" apart from "everything since June". Reviewers fall back to attribution by hand, which is exactly how a rubber-stamp is produced. | `review-request.json` `base_sha` + `git rev-list --count base..HEAD` = 1028 vs `git show --stat HEAD` = 2 files; `git rev-list --count 6a69a8b9..472dc776` = 1. | `dotfiles cli/internal/spec/review_base_test.go` covers the *empty-diff* half of this defect, not the multi-PR-since-base half. | vault / tooling follow-up (dotfiles, not this repo) |
| Question | UNVERIFIED | ops | PR-1a's last box is still open: "`toolkit secrets init/edit` to generate `infra.postgres.password`, then `secrets apply` before the postgres pod starts (else CrashLoop)". Since ADR-066's Vikunja is live on that database, the step was presumably done in a SOPS-enabled context (`verification.md` says `sops` is absent on the dev box). Confirm on the cluster and tick it — or record the disposition — rather than leaving an open box that reads as a CrashLoop waiting to happen. | `tasks.md` PR-1a box; `verification.md` "Env note"; `vikunja.yaml:27-29` wait-for-postgres. No kubectl access from this worktree. | live-cluster check (none named) | spec (`tasks.md`, same edit round as row 2) |

**Not a finding, stated so the absence is on the record:** the `## Abandoned` section does **not**
claim AC1/AC2/AC3 passed, does not silently mark criteria done, and its "what shipped is still in
use" line is the only reuse claim — reproduced above. No test was deleted or weakened in this diff
(`git show --stat fbb35c75` adds no test removal; the only test files it could touch are the two Go
tests from `472dc776`, both still present and passing). No secret material appears in the diff.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | Every claim in the 2-file change verified true, but the archived artifact set contradicts itself on a still-in-force security default (`features.json` vs `proposal.md`) |
| Verification       | B | "what shipped" claims reproduce (`go test -race ./...` green, CI step wired, Postgres+Vikunja manifests); PR-0's own required CI-run URL was never pasted, and the AC table is empty template |
| Scope              | B | HEAD changes exactly the supersession record (ADR-050 note + verification.md); the 1028-commit stated scope is a mechanics artifact, not creep |
| Reliability        | B | AC4 is carried to an existing open ticket (#2494) instead of dropped; residual risk is `tasks.md` pointing a reader at "PR-1b (next)" on a plan ADR-066 rejected |
| Maintainability    | B | Docs-only, no code quality surface; the maintenance cost is a duplicated-and-diverged statement of D5 across two contract files |
| Handoff-readiness  | C | Next step is named (#2494) but stale plan text, vacuous feature commands, and an archive checklist naming the wrong destination make the abandoned folder misleading rather than closed |

**Aggregation:** two C, no D → PASS WITH GAPS at best. Findings 1 and 2 are **REAL Majors whose fix
lands in the contract set**, so the severity×reality path escalates independently — the skill's rule
("Never ask for a contract edit alongside a passing verdict; if the change is worth blocking on, the
verdict is FAIL") decides. More severe of the two paths wins.

### Verdict

**FAIL**

`dotf spec archive` is **not advisable** in the current state — and note the interaction: archiving
with `--force-without-review` would record a `review_bypass:` naming a FAIL this session wrote, which
is worse than the two-minute fix.

Minimum set that flips this to PASS (one edit round, then re-review):

1. **`features.json`** — f4 `behavior` to the amended default: "A Context with no explicit provider
   policy resolves to **no provider** (the request is refused); an explicit cloud grant for that
   context flips the resolution". Leave `state: pending` / `evidence: ""` — do **not** fake a passing
   state on a spec that never ran it.
2. **`tasks.md`** — record the disposition where the liveness is: replace "← IN FLIGHT" / "(next)"
   with the supersession (ADR-066, #2443, AC4 → #2494) and close out the "Closing (whole module)"
   boxes with a one-line disposition each (`wontfix: superseded by ADR-066`), ticking the PR-0/PR-1a
   leftovers that in fact happened and stating which did not.
3. **`verification.md`** (outside the contract set; same commit, costs nothing) — fix the Archive
   checklist to `dotf spec archive --abandoned` → `specs/archive/_abandoned/CONSOLE-002-…/` +
   `status: abandoned`, and add the go-selector blind-spot note if the follow-up is filed rather than
   fixed.
4. Re-run `dotf spec review CONSOLE-002-cross-context-bitacora` — steps 1–2 change two of the three
   digests the launcher recorded in `review-request.json`, so this round cannot be reused.

### Recommended next steps

- **Contract set (fix before the next review, as above):** `features.json` f4 wording; `tasks.md`
  supersession + closing-box dispositions.
- **Carry to #2494 when it is picked up (outside the contract set):** AC4's home must be a call site
  every LLM request crosses (the ticket already says "a policy that one path can bypass is not
  default-deny"). The `TestResolveContextPolicyDefaultDeny` name in `features.json` f4 has no
  referent today; don't inherit it as a spec of record, re-derive the test from the ADR text.
- **Follow-up ticket (tests/toolkit):** widen `tests/test_spec_verifications_select_tests.py` to
  `go test -race ./pkg/... -run TestName` selectors the way it already covers `poetry run pytest -k`
  — f1–f4 sat vacuous for four months because the guard's regex is pytest-only. Root cause: the guard
  was written against the #2180 pytest incident and never generalised to the Go spine (ADR-029).
  File against kubelab or, if it is to cover dotfiles' specs too, against the TOOL-109 line.
- **Knowledge hygiene (in-session, not later):** the reusable defect here is *"an amendment that
  updates the prose but not the machine-readable twin"*. If this recurs on a second spec, it is a
  `docs/lessons/` entry (pattern candidate: amendment must touch every representation of the datum);
  one instance is not yet a pattern — `verification.md`'s promotion answers currently say "no", and
  that stands until a second case appears.
- **Reviewer-pool / process note for the owner (not this spec's blocker):** the launcher resolved a
  base 1028 commits back for a 2-file change. Attribution was doable here because `git log --
  specs/<feature-id>` is short; for a spec folder touched by later unrelated PRs it would not be.
