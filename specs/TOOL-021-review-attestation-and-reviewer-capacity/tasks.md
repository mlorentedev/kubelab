---
tags: [spec, tasks]
created: "2026-08-19"
---

# Tasks - TOOL-021-review-attestation-and-reviewer-capacity

> TDD order. One task = one focused commit. Tick as you go.
>
> **Inline markers:** `[P]` no dependency, safe in parallel. `[AC<n>]` satisfies acceptance criterion #n.

> **Port, do not invent.** Upstream is dotfiles `main` at **2bac1c5**. Every design decision here was made and corrected there; re-deriving them is how the corrections get lost. What must change for kubelab is measured in Part 0 and nowhere else.

> **The two parts ship together and Part 1 is not promoted to required until Part 2 runs.** Measured reason: 20 of 20 recent PRs are authored by the same person and attestation excludes the PR's author, so bots are the only possible attesters here. A required gate without a quota-free reviewer is a deadlock, not a guardrail.

## Part 0 — measure what kubelab differs on (DONE 2026-08-19)

- [x] **CodeRabbit's declined marker is the same as upstream's**: `rate limited by coderabbit.ai`, present as an HTML comment (`<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->`). Machine output, so it ports verbatim. ✓ 2026-08-19
- [x] **kubelab runs a second reviewer upstream does not.** `chatgpt-codex-connector` comments on every PR (#1153, #1155, #1156). On #1155 both it and CodeRabbit were exhausted simultaneously. ✓ 2026-08-19
- [x] **Codex emits no HTML marker — its notice is prose only**: *"You have reached your Codex usage limits for code reviews."* The registry's stated preference for machine markers cannot be honoured for this reviewer. Accepted with eyes open: if the wording drifts the PR reads `pending` instead of `declined`, which is still red, so drift degrades the message and never the verdict. ✓ 2026-08-19
- [x] **The release signature differs from upstream's and is not fixed.** Measured across #767, #804, #806, #842: `.release-please-manifest.json`, `apps/api/{CHANGELOG.md,version.txt}`, `edge/errors/{CHANGELOG.md,version.txt}` — but **#804 carried only three of those**, because release-please opens per-app releases. The gate requires every changed file to appear in the declared set, so a **superset** signature covers both shapes. There is no `versions.conf` here. ✓ 2026-08-19
- [x] **`NAN_API_KEY` already exists in kubelab's Actions secrets** (created 2026-08-16, referenced by nothing). No provisioning step. ✓ 2026-08-19
- [x] **Context files are `AGENTS.md` and `CLAUDE.md`** at the repo root. There is no `.claude/CLAUDE.md` here. ✓ 2026-08-19

## Part 1 — the attestation gate

- [ ] [AC5] **Port `harness/review-attestation.json`** as the reviewer registry, carrying the *why* prose with each entry. Three reviewers from day one: `coderabbitai` (declined marker), `chatgpt-codex-connector` (declined marker, prose, with Part 0's caveat recorded beside it), and `github-actions` (review marker `## PR Reviewer Guide`, for Part 2). `## PR Code Suggestions` is deliberately **not** a review marker — suggestions are not a review.
- [ ] [AC5] Record the release exemption as a **diff signature**, the superset from Part 0. Never by author (release-please runs under a human PAT, so an author rule never fires — verified on #842) and never by branch (any branch can be named to match).
- [ ] [AC1][AC2][AC3] **Port `scripts/check-review-attestation.sh`.** Five states, decided by content: `attested`, `exempt`, `disclosed` → 0; `declined`, `pending` → 1. `declined` and `pending` stay distinct in the output; collapsing them throws away the diagnosis.
- [ ] [AC3] **No reviewer is named anywhere in the script**, and a test enforces it. Every vendor string lives in the registry, including the prose. A vendor name in the script is how "the config is authoritative" quietly stops being true.
- [ ] [AC2] **Attestation requires a non-author who is a repository member or a declared reviewer** (upstream #1071). Discriminator is `authorAssociation`, already in `gh pr view --json reviews`. **`CONTRIBUTOR` is excluded**: it is granted by a merged commit, which a bot earns as easily as a person. The older rule — any login that is not the author — let anything running under the shared automation login attest.
- [ ] [AC4] **Comment-shaped reviews attest on a declared `(login, marker)` pair** (upstream #1047), because a reviewer publishing through the comments API leaves `reviews[]` empty on a PR it genuinely reviewed.
- [ ] [AC4] **Fold the trailing `[bot]` and case before matching a login.** GraphQL returns `github-actions`, REST returns `github-actions[bot]`; matching raw makes the verdict depend on which API produced the payload (upstream #1033).
- [ ] [AC1][AC9] **Port the escape as label *and* body section, never one alone** — `merged-unreviewed` plus `## Unreviewed merge rationale`. Proceeding on an unreviewed PR is allowed; proceeding silently is not.
- [ ] **The check observes and never acts.** It must not re-trigger a rate-limited reviewer: a gate that spends the quota it measures perturbs its own subject. (Measured moot upstream anyway — an explicit re-review does not reclaim a spent slot.)
- [ ] [AC4] **Port the `workflow_run` re-evaluation** (upstream #1052, #1056). Comments authored with `GITHUB_TOKEN` emit **no events at all**, so `issue_comment` never fires for our own reviewer and the verdict would be computed seconds after the PR opens and never revised. Load-bearing, not an optimisation.
- [ ] [AC10] **Publish a commit *status*, not a check-run.** A check-run belongs to the run that created it and can never be revised, so a later attestation could not clear it.
- [ ] Tests: `tests/` fixtures for each state, **including a fixture per declined reviewer**. Fixtures must be written from real payloads in both GraphQL and REST spellings.
- [ ] [AC1] **Show the gate failing on a real unreviewed PR before trusting it**, not only passing on a reviewed one. This repo has already shipped a gate whose 35 green unit tests agreed with each other and with nothing else (#1143); fixtures cannot catch a shape the fixtures do not use.
- [ ] [AC8] Exercise the exemption on a **real release PR** — exempt, not `pending`.

## Part 2 — a reviewer without an account-wide quota

- [ ] [AC6] **Add `.pr_agent.toml`**, ported with kubelab's values: `repo_context_files = ["AGENTS.md", "CLAUDE.md"]`, `fallback_models = []`, explicit token budget (NaN models are absent from LiteLLM's registry, so an unstated budget truncates the diff).
- [ ] [AC6] **No cheap fallback model**, and say why in the file. If the reviewer fails, Part 1 reports `declined` and the PR goes red — a loud absence. A latency-optimised fallback would trade that for a quiet rubber stamp, and this repo already holds the opposite policy for the spec-review pool.
- [ ] [AC7] **`[ignore] glob` excludes `infra/config/secrets/**` and `**/*.pem`** before the model call. kubelab is public, so the source is not the concern; credential material is.
- [ ] [AC6] **Rewrite `extra_instructions` against kubelab's doctrine**, not dotfiles'. Name the linters this repo runs (ruff, mypy, pytest, yamllint, markdownlint) as the things *not* to restate. Do **not** carry the shell prohibited-pattern instructions or any reference to `.claude/CLAUDE.md`: an instruction naming a source the reviewer cannot read reads as rigour and asserts nothing.
- [ ] **Do NOT port the `HARNESS COMPLIANCE` block.** Measured upstream: asked for on every review, delivered 1 time in 16 (dotfiles #1072). An instruction ignored 94% of the time is a comment that looks like a control.
- [ ] **Do NOT port `ignore_pr_source_branches`.** Measured inert upstream — loaded and never consulted on the Action path, so release PRs are reviewed anyway (dotfiles #1073, whose recommendation is deletion). Installing it here would add a setting that looks like a decision and asserts nothing. Part 1's diff-signature exemption is the half that works.
- [ ] [AC6] **Add `.github/workflows/pr-agent.yml`**, pinned to a tag verified to exist and to carry an `action.yaml`. Port the concurrency group **verbatim**, including the event name in the key: without it a comment-triggered run shares the group with the in-flight PR run and `cancel-in-progress` kills the review (measured upstream on #1037/#1038 — both green, zero reviews).
- [ ] [AC6] `auto_describe: false` — `describe` rewrites the PR body, and the bodies here carry hand-written measurement tables that are the part worth reading.
- [ ] [AC6] Enable the push path explicitly (`handle_push_trigger`, `push_commands: ["/review"]`). `synchronize` in `pr_actions` asserts nothing — upstream routes it separately — and omitting `push_commands` silently reinstates `describe` on every push.
- [ ] [AC9] **Demonstrate the reviewer's own failure produces a red PR** — bad credential or unreachable endpoint — not a green one.
- [ ] [AC10] **Only now**, promote the **commit status `review-attestation`** — never the check-run `attestation` — to required in branch protection. Naming the job would block every PR where a second event arrives mid-run, which is now the common case because a reviewer speaking is itself a trigger; those runs are cancelled by design and a cancelled run can never be made to conclude green. Verified on #1165: `conclusion=cancelled` on the job, `success` on the status, same SHA, and show an unreviewed PR reporting `mergeStateStatus: BLOCKED` rather than merely a failing check. Branch protection is a setting no test in this repo can see.
- [ ] [AC11] Assert in a test that nothing in the change enables auto-merge.

## Closing

- [ ] Open the follow-up ticket for the retirement decision, whose first question is the one this spec declined to guess: **what observation retires a reviewer?** Not a date.
- [ ] `verification.md` carries the transcript for every criterion, produced in this session — including the two failures the gate must exhibit.
- [ ] #1140 closes when this spec archives, not before. Part 1's PR references it **without** a closing keyword.
