---
id: "TOOL-021-review-attestation-and-reviewer-capacity"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-19"
issue: "mlorentedev/kubelab#1140"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-021-review-attestation-and-reviewer-capacity

## Why

<!-- from issue #1140: CI-GATE-011: the CodeRabbit status reports success when no review ran — 8 of 8 PRs, 7 already merged -->

A PR in this repo can be merged with a green `CodeRabbit` check and no review behind it. CodeRabbit's free tier allows roughly one review at a time account-wide; when the quota is spent it posts *"Review limit reached — you've reached your PR review limit, so we couldn't start this review"* and **the commit status still reports SUCCESS**. Nothing in the repo distinguishes "reviewed" from "not reviewed", so the two cases are indistinguishable on the PR page. Measured on every PR opened 2026-08-17/18 — 8 of 8 unreviewed, 7 already merged (#1140) — and again on 2026-08-18 with #1153, #1155 and #1156, taking it to 11 of 11. This is not a vendor complaint: `pr-stewardship` already binds every agent here to disposition reviewer output, and that obligation is unsatisfiable when "no review ran" renders as a green tick.

## What

Two changes, in order, because the second is unsafe without the first.

**Part 1 — a review-attestation gate.** A required check answers one question: *did a review actually happen on this PR?* It never asks who performed it or whether it was any good; a human review attests exactly as well as a bot's. A reviewer's "I could not review" notice is classified as `declined`, not as a review, and turns the PR red. The reviewer registry lives in a config file, so changing or adding a reviewer is a data edit rather than a code change.

**Part 2 — a second reviewer without an account-wide hourly quota**, PR-Agent (`The-PR-Agent/pr-agent`, MIT) driven by NaN cluster inference, posting inline comments on the diff. It runs **alongside CodeRabbit for a bounded window**, not instead of it: on a public repo CodeRabbit is not inline-crippled, so what is scarce here is review *capacity*, not review *quality*, and retiring a working reviewer before measuring the replacement would trade a known tool for an unmeasured one.

Observable after both: a PR that nobody reviewed cannot be green, and the ordinary reason a PR went unreviewed — the quota — stops occurring.

## Out of scope

- **Retiring CodeRabbit.** Deliberately deferred to a decision with data from the parallel window. Recorded here so the window has a declared end rather than becoming permanent by omission.
- **Judging review quality.** The gate asks whether a review happened, never whether it was good. Any attempt to score a reviewer turns the gate into an opinion and gives it a way to be wrong.
- **The spec-level adversarial review** (`dotf spec review`, reviewer pool, `review.md`). A different gate with a different purpose, already working. The two must not be merged, and the model-eligibility policy that governs the spec reviewer must not leak into this one.
- **Fixing CI-GATE-013 (#1157).** The spec gate reads closing keywords inside code blocks where GitHub does not. Adjacent, separately ticketed, and not a dependency.
- **Auto-merge in any form.** Nothing here may merge a PR. The gate makes an unreviewed PR visible; a human still merges it.

## Risks / open questions

- **A gate that can only report red is worthless, and one that can only report green is worse.** The failure this exists to end is a check that is green when nothing happened, so the gate must be shown failing on a real unreviewed PR *before* it is trusted — not merely passing on a reviewed one. Both directions, against the committed tree, not fixtures: this repo has already shipped one gate whose 35 green unit tests agreed with each other and with nothing else (#1143).
- **Telling a review from a notice must key on content, not author.** `pr-stewardship` states the rule and the reason: *"a review names files, lines, or claims; a notice talks about the review itself"*. Matching on the reviewer's login would classify the rate-limit notice as a review, because the same account posts both.
- **PR-Agent publishes through the comments API, not the reviews API.** Running under `GITHUB_TOKEN` it appears as `github-actions` and its output never enters `reviews[]`, so a gate that reads only the reviews API sees every PR-Agent-reviewed PR as unattested. This is measured upstream (dotfiles #1045) and is a defect this port would inherit silently.
- **The two GitHub APIs disagree on the login string.** GraphQL returns `github-actions`, REST returns `github-actions[bot]`. Matching the raw string makes the gate depend on which API produced the payload (dotfiles #1033).
- **Release PRs need an exemption on both halves or neither.** PR-Agent's ticket-compliance pass reads the CHANGELOG's issue references, looks for their code in the diff, and reports "none of the above requirements are fulfilled" on every release, structurally. Excluding release branches from the reviewer *without* a matching gate exemption produces a PR with no reviewer output that the gate correctly calls `pending` and that nothing can ever clear — an unreachable state, filed upstream as #1061. **One half alone is worse than neither.**
- **No cheap fallback model.** If the reviewer fails, the gate reports `declined` and the PR goes red — a loud absence. Falling back to a latency-optimised model would trade that for a quiet rubber stamp, and this repo already holds the opposite policy for the spec-review pool. Two files with opposing policies on who may review is its own defect.
- **Diffs leave the repo at the model call.** kubelab is public, so the source is not the concern; credential material is. `infra/config/secrets/**` and `**/*.pem` must be excluded by path *before* the call, and the exclusion belongs in a config file rather than in memory.
- **Copying dotfiles' config verbatim would misconfigure it.** Its `repo_context_files` names `.claude/CLAUDE.md`, which does not exist here, and its reviewer instructions cite a shell prohibited-pattern table that is also not here — while naming linters (shellcheck, bats, golangci-lint) this repo does not run instead of the ones it does (ruff, mypy, pytest, yamllint, markdownlint). An instruction naming a source the reviewer cannot read is the same shape as a guard citing a check it cannot run: it reads as rigour and asserts nothing.
- **Open question — the parallel window's end condition.** "Bounded" needs a criterion that is not a date: what observation retires CodeRabbit, or retires PR-Agent? Unresolved; must be answered before Part 2 closes, not before it starts.

## Acceptance criteria

- [ ] A PR whose only reviewer output is a "review limit reached" notice is **red**, demonstrated on a real PR in that state rather than on a fixture.
- [ ] A PR with a genuine review is **green**, and a PR with no reviewer output at all is red — the three states are distinguished, and the second is shown to still pass after the gate lands.
- [ ] Classification keys on comment **content**, not on the author's login, demonstrated by a case where the same account posts both a review and a notice.
- [ ] A PR-Agent review — published through the comments API as `github-actions`, absent from `reviews[]` — attests successfully, and does so whether the payload came from GraphQL or REST.
- [ ] Adding or changing a reviewer is a **config edit with no code change**, demonstrated by adding one to the registry.
- [ ] PR-Agent posts inline comments on the diff of a real PR in this repo, with `NAN_API_KEY` as its only credential.
- [ ] No file under `infra/config/secrets/` or matching `**/*.pem` is ever sent to the inference endpoint, demonstrated by a PR touching one and the path filter excluding it.
- [ ] A release PR is neither reviewed by PR-Agent nor left permanently `pending` by the gate — both halves of the exemption are exercised on one real release PR.
- [ ] The reviewer's own failure (unreachable endpoint, bad credential) produces a **red** PR, not a green one, demonstrated by injecting the failure.
- [ ] Nothing in the change enables auto-merge, asserted by a test rather than by inspection.

## References

- Bitácora board: `mlorentedev/kubelab#1140` (Part 1's work-gate). Part 2 needs its own issue before it starts.
- Upstream implementations to port, not to invent: dotfiles `GUARD-002-review-attestation` (#906) and `TOOL-013-pr-agent-reviewer` (#786), both merged to `main`. The ordering here is theirs and is deliberate — their attestation registry records that building the gate first is what stops a replacement reviewer inheriting the blind spot.
- `docs/lessons/ci-automation/lesson-348-*` — the closing-keyword findings from the same investigation; unrelated mechanism, same "the tool answered exactly what was asked, and the question was wrong" family.
- Related: #1157 (CI-GATE-013), adjacent and out of scope.
