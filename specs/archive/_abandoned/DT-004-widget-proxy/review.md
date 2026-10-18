---
spec: "DT-004-widget-proxy"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "0556cbae9bb3c3329a8c2062c51787d35b5a724a"
reviewer: "nan/deepseek-v4-flash"
date: "2026-10-18"
---

## Adversarial review

**Scope**: `DT-004-widget-proxy` — abandonment of the spec, not an implementation. The change under review is the archival record: the scaffolded triad (`proposal.md`, `tasks.md`, `verification.md`) plus the two commits that touch it since the spec's work began.
**Sources**: `specs/DT-004-widget-proxy/{proposal,tasks,verification}.md`; `git diff 4576d8d8f1cf875d19698e20016732c53b9b3b2d...HEAD` (2435 files, 247180+/36885−, because the stated base is 1129 commits back — 2026-05-20, the commit immediately before this spec was scaffolded); the spec-attributable commits are `d9108383` (scaffold), `3756c81c` (issue-gate fix), `0556cbae` (abandonment: verification.md + CLAUDE.md + ADR-035). Rest of the range is unrelated history and is **not** reviewed here.

### Scope note on the base

The base the launcher resolved (`4576d8d`, 2026-05-20 05:25 +0200, PR #184) is the commit *before* this spec existed, so `base...HEAD` is the entire repository history since then, not one change. Reviewing that as "the whole change" would mean auditing ~1129 unrelated PRs. I reviewed every file in the range that the spec actually owns (listed above) and state that limitation rather than implying full-diff coverage. If the intent was "everything since the spec's work started", the base is correct and this note is the honest boundary of the pass.

### Spec and task alignment

- **Proposal ACs (AC1–AC7) are all `[ ]`** — correct, not a finding: nothing was built, so nothing may be ticked. An abandonment is not a partial implementation.
- **`tasks.md` ticked boxes**: exactly two (`[x] proposal.md complete, AC1–AC7 testable`, `[x] Both BLOCKERS resolved`). The claim in `verification.md` — "The only ticked tasks are the two spec-writing ones" — is **true** (read of `tasks.md`).
- **"Nothing was built"**: verified. `apps/` contains only `api` and `README.md`; `grep -rIl widget-proxy` finds nothing outside this spec folder, `docs/adr/adr-035`, `adr-034`, `adr-057` and archived specs; no `widget-proxy` manifests, generator, or `widgets.staging.kubelab.live` host anywhere.
- **"no `MIDDLEWARE_CATALOG` entry"**: verified — `toolkit/features/k8s_middlewares.py:72` reads `MIDDLEWARE_CATALOG: list[MiddlewareSpec] = []`.
- **Premise claim** ("the Homepage cockpit was retired"): verified against the live board — `gh issue view 2416` → **CLOSED**; `#2446` → **MERGED**; `#2451` → **MERGED**.
- **"ADR-034's language decision stands on its own"**: the ADR exists and does record the Go decision (`docs/adr/adr-034-polyglot-apps-language-per-service.md`, decision + anchored table). The claim is substantively correct; see Finding 3 for what was left behind in that document.
- **Cited ticket `#2443`**: `gh issue view 2443` → OPEN, titled *"chore(specs): bring active specs back under the WIP limit"*. It is not an abandonment decision but the governing ticket, whose acceptance reads *"each archive cites its review and a reason (finished, integrated or obsolete)"*. Citing it reads as though #2443 decided the abandonment; it authorised it. Wording-only (Finding 5).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | record hygiene | `verification.md` is archiving with its template still unfilled: `## Evidence` holds `- [ ] Criterion 1 -> commit \`<hash>\` / test \`<name>\``, `## Test status` holds `` `<command> -> <output / coverage %>` ``, and `## Decisions made during implementation` ends in two bare `-` bullets. An archived record that reads like pending work is the opposite of an audit trail. | `sed -n` of `verification.md`; placeholders present in HEAD | UNTESTED (no gate asserts a spec file carries no `<placeholder>` tokens) | spec — `verification.md` (outside the contract set, editable without invalidating this review) |
| Minor | REAL | ADR consistency | The commit retired **ADR-035's** `widget-proxy` row but left **ADR-034's** anchored-decisions table row `| apps/widget-proxy (DASH-DT-004) | Go | … |` and its reference `specs/DT-004-widget-proxy/proposal.md` untouched. After `dotf spec archive` moves the folder, that reference is a dead path, and the twin tables disagree about the same abandonment. | `grep -n 'DT-004\|widget' docs/adr/adr-034-polyglot-apps-language-per-service.md` → lines 13, 19, 44, 51, 57 still live; `adr-035` row changed in `0556cbae` | UNTESTED (no test asserts ADR→spec paths resolve) | code/docs — `docs/adr/adr-034-*.md` |
| Minor | REAL | spec contract | `tasks.md` states *"Spec emits a sibling `features.json`"* and embeds a 7-entry JSON block, but **no `features.json` exists** in the folder (the launcher recorded an empty digest for it, and #2443 itself lists DT-004 among *"No `features.json`, the oldest"*). Abandoning without one is defensible; the archived `tasks.md` asserting one exists is not. | `ls specs/DT-004-widget-proxy/` → no `features.json`; `review-request.json` `contract_digests.features.json: ""` | UNTESTED | spec — but `tasks.md` is **contract set**: ticket it, do not edit before archive |
| Minor | THEORETICAL | archive checklist | The checklist still asks to tick *"Backlog entry in vault `11-tasks.md`"*. Task state no longer lives in the vault (ADR-018) and #465's own body says *"Migrated from the kubelab vault backlog (11-tasks.md) per ADR-018"*. A step pointing at a retired artefact cannot be honestly ticked, so the checklist as written makes the archive look incomplete. | `verification.md` §Archive checklist; `gh issue view 465` body | UNTESTED | spec — `verification.md` |
| Minor | REAL | board state | Tracking issue **`kubelab#465` is still OPEN** and its body still advertises the spec as implementation-ready (*"Both BLOCKERS resolved in spec … 5-task breakdown ready for implementation"*). Nothing in the checklist mentions closing it; if `dotf spec archive` does not close it, the board contradicts the archive. | `gh issue view 465 --json state,body` → OPEN, body as quoted | UNTESTED | ticket/board — close #465 as part of the archive, or add the step to `verification.md` |
| Minor | REAL | wording | `CLAUDE.md` now reads the plugin *"stays registered for **them**"* where the antecedent list was reduced to one entry (`Pollex public`/AI-004). Grammatical residue of the edit; not incorrect, just imprecise in the sentence a future reader consults. | `git show 0556cbae -- CLAUDE.md` | UNTESTED | docs — `CLAUDE.md` |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | The abandonment is factually right on every claim I could test (nothing built, cockpit retired, catalogue empty, test green); the two omissions are record-level, not behavioural. |
| Verification       | B | Claims are reproducible and I reproduced them (`gh`, `grep`, `pytest`), but the spec's own Evidence/Test-status sections are stubs, so the proof lives in this review rather than in the artefact. |
| Scope              | B | Spec-attributable change is tight and on-premise (3 files in HEAD); the stated base spans 1129 unrelated commits, which makes PR-level scope unmeasurable — see the scope note. |
| Reliability        | B | A docs-only archive has no error paths; the action is idempotent and reversible by git. No observable risk. |
| Maintainability    | C | Two documents that point at this spec were left stale (ADR-034 row/path, the vault-checklist step) and the archived verification keeps `<hash>` placeholders — clarity debt in the permanent record. |
| Handoff-readiness  | C | Abandonment reason, lesson/ADR/pattern decisions and their justifications are present and good; the record is not self-sufficient while ADR-034 disagrees and #465 stays open. |

### Verdict
PASS WITH GAPS

No Blocker and no REAL Major: the change asserts an abandonment, and every substantive assertion survived refutation. The gaps are hygiene in the permanent record (unfilled template, a sibling ADR left half-retired, a tracking issue still open, a checklist step aimed at a retired vault file).

### Recommended next steps

Contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed** under this verdict — an edit there invalidates the review. Disposition the rest in `verification.md` or a follow-up ticket:

- Fill or delete the `## Evidence` / `## Test status` / `## Decisions` stubs in `verification.md` so the archived record carries no `<placeholder>` text (Finding 1).
- Amend ADR-034: annotate the `apps/widget-proxy` row as abandoned (`#2443`/`#2416`) and repoint the `specs/DT-004-widget-proxy/proposal.md` reference at `specs/archive/…` after the move (Finding 2).
- Replace the `11-tasks.md` checklist step with "close tracking issue #465 as abandoned" per ADR-018, and confirm the issue is closed when the archive lands (Findings 4, 5).
- Ticket the `features.json` absence named in `tasks.md` (Finding 3) — contract-set fix, so a follow-up ticket, not an edit now.
- Tighten the "registered for them" antecedent in `CLAUDE.md` (Finding 6), or decline it as too small to matter — state which.
- The archive itself is **advisable** in the current state: the substance is correct, and the four record-hygiene items are all editable outside the contract set.
