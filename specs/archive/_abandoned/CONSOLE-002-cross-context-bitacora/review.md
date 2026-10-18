---
spec: "CONSOLE-002-cross-context-bitacora"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "67479fdff1f5eb7c5cf4d419b1bc04d455dacb19"
reviewer: "nan/qwen3.8-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: CONSOLE-002-cross-context-bitacora — round 2, the re-review after round 1's FAIL. Change
under review = the abandonment/supersession record plus the review-application commit.
**Sources**: `specs/CONSOLE-002-cross-context-bitacora/{proposal,tasks,verification,features}.md`;
stated base `6a69a8b9c199ff045a3e71778744f228b470b556...67479fdff1f5eb7c5cf4d419b1bc04d455dacb19`;
round-1 verdict (`review-round1.md`, `fbb35c75`); ADR-050 + its 2026-10-01 amendment; ADR-051;
ADR-066; `.github/workflows/ci-pipeline.yml`; `apps/api/src`; `toolkit/features/secrets_manager.py`;
`dotfiles cli/internal/spec/{archive,review}.go`; issues #711, #2443, #2494, #2501.

**Attribution note (same mechanic as round 1, restated because it bounds what I certified).** The
launcher's base is the parent of the spec's first commit, but the spec's work landed on `master` as
five separate squash-merges over four months, so `git diff base...HEAD` spans ~1029 commits / 2215
files / +216,210 lines and is not a reviewable unit. `git log --oneline -- specs/CONSOLE-002-…/`
returns exactly five commits — `472dc776` (PR-0 harness), `c1db49e1` (PR-1a Postgres), `d7d58861`
(ADR-050 D5 amendment), `fbb35c75` (supersession record), `67479fdf` (this HEAD: apply the review).
I reviewed those, the artifact set they leave behind, and every claim the HEAD commit newly asserts.
I did not audit the ~1024 unrelated commits; the archive gate certifies this spec, not `master`.

**What HEAD actually changes** (`git show --stat 67479fdf`): `features.json` 1 line, `tasks.md` +25/−6,
`verification.md` +21/−4 (Review dispositions + corrected archive checklist), plus launcher state
(`review-request.json`, `review.md`). No code, no test added/deleted/weakened, no secret material, no
injection or authz surface. This is exactly the contract-set round-1 fix set and nothing else.

### Round-1 blockers: closed, and re-verified rather than trusted

- **Real Major 1 (`features.json` f4 said the abandoned default).** Closed. f4 now reads "resolves to
  no provider and the request is refused; an explicit cloud-provider grant for that context flips the
  resolution (… ADR-050 D5 as amended 2026-10-01; carried by kubelab#2494)". I compared it line by
  line against `proposal.md` AC4 and ADR-050's amendment bullet ("A Context with no explicit provider
  policy resolves to **no provider**. A routing decision for it is refused, not degraded.") — the two
  contract representations now agree, and `state: "pending"` / `evidence: ""` were *not* faked into a
  passing claim. ADR-050's D5 body still says "local-only (Ollama)" but carries the amendment
  parenthetical pointing at the 2026-10-01 section: normal ADR practice, not a stale twin (checked
  with a repo-wide grep for the retired default — no other live representation).
- **Real Major 2 (`tasks.md` read as live work).** Closed. Banner names the supersession (ADR-066,
  #2443, AC4 → #2494); "← IN FLIGHT" → "(shipped, #714)"; "(next)" → "(never started; superseded by
  ADR-066)"; the Closing checklist carries a section-level `wontfix` disposition; both surviving PR-0
  boxes carry their own "Disposition 2026-10-18: not recorded" line rather than a silent tick.
- **Round-1 "Question / UNVERIFIED" (the PR-1a deploy box) — now resolved in the reviewer's favour, by
  reproduction.** The box was ticked on the claim `toolkit secrets audit --env prod` → `PROD —
  121/121`. I did not take that: I ran `SecretsManager().audit("prod")` in-process against the
  reviewed `secrets_manager.py` and printed **counts only** (no values, per the repo's secret-safety
  doctrine): `present=121 missing=0 malformed=0`, and `infra.postgres.password ∈ present`. The
  printed report format is `f"{env.upper()} — {present}/{total}"` (`cli/secrets.py:430`), so the quoted
  string is what that result renders as. Separately: the catalog's prod subset is exactly 121 entries
  (denominator is the catalog, not a hand-picked number), and `SecretSpec(key_path="infra.postgres.password", …
  envs=("staging", "prod"))` confirms "catalogued for staging and prod". The tick is honest evidence,
  not a hopeful close.
- **Round-1 Minor (vacuous `./internal/board/...` commands + pytest-only guard).** Properly
  dispositioned: `gh issue view 2501` → **OPEN**, "The features.json verification guard only reads
  pytest commands, so a go test selector that selects nothing passes", body names this spec, the
  nonexistent packages and the root cause. I confirmed the package never existed independently:
  `ls apps/api/src/internal` → `api constants health models services`; `git log --all --
  apps/api/src/internal/board` → empty.
- **Round-1 Minor (archive checklist named the wrong destination).** Closed and verified against the
  tool: `dotf spec archive --help` — "or `specs/archive/_abandoned/` under `--abandoned` … rewrite the
  proposal status to archived/abandoned"; `archive.go:320-321` sets `newStatus = "abandoned"` and
  `target = specs/archive/_abandoned/<id>`; `archive_test.go:341-347` pins both. The rewritten
  checklist matches the actual behaviour.
- **No `[AGENT-DRAFT]` trap, re-checked for the files this round added.** `FindUnresolvedTags`
  (`archive.go:212-238`) walks *every* file in the folder but skips `IsReviewState` names — and that
  list includes `review.md`, `review-round1.md`, the transcript and `review-request*.json`
  (`archive.go:154-196`), precisely so a review cannot make the gate unpassable. The only tag in the
  author-written files is `proposal.md:13`, backtick-wrapped and stripped by `stripCodeSpans`. The
  launcher's new 552-file-ish transcript therefore does not block the move.

### Independent checks run this round (not assertions read from docs)

| Command | Result |
|---|---|
| `git show --stat 67479fdf` | 3 author-written spec files + review state; no code, no tests touched |
| `poetry…python -m pytest tests/test_spec_gate.py tests/test_spec_verifications_select_tests.py -q` | **68 passed** — the wording edit breaks no spec gate |
| `SecretsManager().audit("prod")` (counts only) | present=121, missing=0, malformed=0; `infra.postgres.password` present |
| `SECRET_CATALOG` count where `'prod' in envs` | 121 — matches the quoted denominator |
| `head -3 apps/api/src/go.mod` | `go 1.26.0` — confirms the "Moot 2026-10-18" note |
| `grep -n "Test API code" .github/workflows/ci-pipeline.yml` | line **116**, exactly as the disposition cites |
| `ls apps/api/src/internal` + `git log --all -- …/internal/board` | no `board`, never existed in history |
| `gh issue view 711 / 2443 / 2494 / 2501` | all OPEN; the checklist's "#711 closed as superseded" is a genuine remaining step, not stale text |
| `dotf spec archive --help` + `archive.go` / `review.go` | `PASS-WITH-GAPS` is a non-blocking verdict (`Verdict.Blocks()` = only FAIL blocks); promotion pre-flight satisfied — all three answers are `no: <reason>` |

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) | Disposition |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|-------------|
| Minor | REAL | process / tracked debt | The launcher base-resolution defect from round 1 was dispositioned as "not this repo's defect… belongs to the dotfiles review launcher" **without naming a ticket**. The standing order is *noted = recorded*: a disposition that identifies the owner but files nothing leaves the defect untracked, and round 3 of any later spec will hit it again (HEAD's `review-request.json` still carries `base_sha: 6a69a8b9`, i.e. ~1029 commits for a 3-file change). | `verification.md` Review dispositions item 5 (no issue number); `review-request.json` `base_sha`; `git rev-list --count 6a69a8b9..HEAD` ≈ 1029 vs `git show --stat HEAD` = 3 author files. | UNTESTED — `dotfiles cli/internal/spec/review_base_test.go` covers only the empty-diff half of this defect, not the multi-PR-since-base half. | vault / tooling (dotfiles issue, not this repo) | **Ticket it in dotfiles** (or record an existing issue number in `verification.md`, which is outside the contract set and costs no re-review). Not this spec's blocker. |
| Minor | REAL | issue hygiene | #2501's body states as completed fact that "That spec was archived as abandoned on 2026-10-18 (#2443), so the instance is gone." At HEAD it is not archived: the folder is still the active `specs/CONSOLE-002-cross-context-bitacora/`. Cost is small but real — whoever picks up #2501 looks for an archived folder that isn't there, and the "instance is gone" framing weakens the repro. | `gh issue view 2501 --json body`; `ls specs/CONSOLE-002-cross-context-bitacora` present, `ls specs/archive/_abandoned/CONSOLE-002-*` absent; `git status` shows the folder tracked at its active path. | UNTESTED (GitHub text, not code) | outside the repo — the issue body | **Apply on archive**: one comment on #2501 ("spec archives with this PR; folder lands at `specs/archive/_abandoned/…`"). No contract edit needed. |
| Minor | REAL | artifact self-description | `verification.md` item 2 says `tasks.md` got "a disposition on every open box". 10 of the 12 remaining open boxes are dispositioned at **section** level (4 under PR-1b, 6 under "Closing (whole module)"), 2 carry their own line. The section notes are immediately above their boxes and unambiguous, so the reader is not misled; the sentence just over-claims granularity. | `grep -n "^- \[ \]" tasks.md` → 12; only 84 and 104 have inline dispositions; 122-126 and 141-144 carry the notes. | UNTESTED (prose) | outside the contract set — `verification.md` | **Decline as written** (or reword to "a disposition on every open box, per section"). Explicitly *not* a request to edit `tasks.md`: its section-level notes are a legitimate record, and a contract edit now would stale this verdict. |
| Minor | THEORETICAL | archive mechanics | After `dotf spec archive --abandoned`, all three rewritten Archive-checklist items will still print as unticked human leftovers. `tickArchiveChecklist` skips the `status: archived` and `folder moved` fragments when `abandoned` is set (`item.notAbandoned && abandoned → continue`), and the third item is board-side by design. So the corrected wording is right and the boxes still won't self-tick — a surprise the operator should expect rather than a defect introduced here (the old wording was not tickable in abandoned mode either). | `dotfiles cli/internal/spec/archive.go:384-410`; `archive_test.go:727-747` (abandoned path). | covered by `archive_test.go` for the route, not for the checklist interaction — the gap lives in dotfiles, not this repo | vault / tooling (dotfiles follow-up, optional) | **Accept + note in the PR body**: tick the two route boxes by hand after the move. |
| Question | UNVERIFIED | ops | "Vikunja runs on this database (ADR-066)" and the CrashLoop-avoidance half of the PR-1a claim are verified at manifest + secret-catalog level only (`vikunja.env` `VIKUNJA_DATABASE_TYPE=postgres`, `vikunja.yaml` wait-for-postgres init container, ADR-066 status) — not from the live cluster, which a worktree cannot reach. The secret is present in the prod vault, which is the precondition the box asserts; pod state is upstream of this spec. | Round 1 reproduced the manifest side; `kubectl` unavailable/forbidden from here. | live-cluster check (none named) | none (out of this spec's reach) | **Pass to #2443's close check**; the board, not the spec, owns the live claim. |

**On the record as absent, not as praise:** no acceptance criterion was silently marked done — the
`## Evidence` AC table keeps `[ ]` on all four and `features.json` keeps `"state": "pending"` for all
four; `dotf spec archive` reads neither as a gate. No test was deleted or weakened by HEAD. No secret
value appears anywhere in the diff (the disposition cites counts and key paths only, which is what
the command is built to print). The three archive pre-flights — draft tags, fresh non-FAIL review,
answered promotion candidates — are each satisfied by this state.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Both round-1 REAL Majors closed and re-verified against ADR-050 + `proposal.md`; the remaining findings are minors outside the passing path |
| Verification       | B | The headline claim (`PROD — 121/121`, `infra.postgres.password` present) reproduces in-process; `go.mod`/CI-line/package-absence claims all confirm; PR-0's CI-run URL is still unrecorded — honestly, not faked |
| Scope              | B | HEAD touches exactly the three files the review named, plus launcher state; no drive-by edits |
| Reliability        | B | AC4 carried to an open #2494; vacuous-command guard carried to an open #2501; nothing in the record now points a reader at work ADR-066 rejected |
| Maintainability    | B | Docs-only; the D5 datum is stated once per representation and the representations agree |
| Handoff-readiness  | B | Correct archive route, statuses, dispositions and next steps (#711 close, #2494, #2501); residual is the un-ticketed dotfiles defect and #2501's anticipatory wording |

**Aggregation:** all six dimensions B or above → PASS path on the rubric. No Blocker and no Major open
(both round-1 REAL Majors are closed, not merely re-tagged); the open items are Minors, each with a
disposition above. Severity×reality and rubric agree, so the verdict is the tracked-gaps form rather
than a clean pass: two REAL Minors are still un-tracked outside this repo.

### Verdict

**PASS WITH GAPS**

`dotf spec archive CONSOLE-002-cross-context-bitacora --abandoned` **is advisable** in the current
state. `review.go:41` treats `PASS-WITH-GAPS` as non-blocking (only `FAIL` blocks), the contract digests in
`review-request.json` match what I read, and nothing below requires touching `proposal.md`,
`tasks.md` or `features.json` — an edit to any of those would stale this verdict, so do not make one.

### Recommended next steps

Every item here is **outside the contract set**, so all of them can be applied after this verdict
without invalidating it. Set in brackets.

- **Open PR / archive commit [outside]:** run the archive with `--abandoned`, then tick the two route
  boxes by hand (they are skipped by design in abandoned mode — see row 4).
- **On #2501 [outside — GitHub]:** comment that CONSOLE-002 is archived with this change and give the
  landing path, so the body's "already archived" claim becomes true rather than premature.
- **In dotfiles [outside]:** file the launcher base-resolution defect (multi-PR-since-base ⇒
  reviewer handed ~1000 commits for a 3-file spec change), or point the disposition at an existing
  issue and cite that number in `verification.md`. That closes the only tracked-debt gap this round
  found; the fix belongs in `cli/internal/spec/review_base*.go`, not here.
- **Carry to #2494 when picked up [outside]:** do not inherit `TestResolveContextPolicyDefaultDeny`
  as the spec of record — it has no referent (the package never existed). Re-derive the test from
  ADR-050's amendment bullet, and place the gate where every LLM routing decision crosses, since "a
  policy one path can bypass is not default-deny".
- **Knowledge hygiene [outside — decide at PR time]:** the reusable defect found in round 1 — an
  amendment that updated the prose but not the machine-readable twin — is now a *closed loop*:
  detected, fixed, re-reviewed in the same spec. One instance, one project, so it stays a
  `docs/lessons/` candidate and not a pattern; `verification.md`'s promotion answers already say
  `no: one project`, which is the honest record. If a second spec shows the same divergence, that is
  the promotion trigger.
