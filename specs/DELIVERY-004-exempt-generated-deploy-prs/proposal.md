---
id: "DELIVERY-004-exempt-generated-deploy-prs"
status: draft # draft | implementing | verifying | archived
type: spec
created: "2026-09-04"
issue: "mlorentedev/kubelab#1619"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# DELIVERY-004-exempt-generated-deploy-prs

> **Naming**: file lives at `<repo>/specs/DELIVERY-004-exempt-generated-deploy-prs/proposal.md`. `DELIVERY-004-exempt-generated-deploy-prs` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1619: DELIVERY-004: generated deploy and promote PRs consume 38% of review capacity and have nothing to review -->

**23 of the last 60 pull requests in this repository are machine-generated deploy or promote PRs, and every one of them goes through the full reviewer circuit while carrying nothing a reviewer can act on.** Each is two lines — an app version in `values/<env>.yaml` and the same value in the regenerated overlay — produced by `toolkit deployment promote` (ADR-046 D6) and already guaranteed byte-for-byte against the generator by the config-drift gate (ADR-027).

The cost is not theoretical and lands on human work: #1614, #1611, #1546 and #1564 received reviewer capacity notices instead of reviews, and #1546 and #1564 were merged unreviewed and declared as such. Separately, generated PRs displace human ones out of pr-agent's single pending concurrency slot (#1203; second measurement filed there today — PR #1617, run `33833277310`, `conclusion: cancelled`, `steps: 0`, job never executed). Staging pays the rest: #1560 took 11h and #1590 took 19h30m from bot-opened to merged, against ADR-046 D3, which specifies staging as Continuous Deployment with **"No human gate"**.

## What

**One predicate — an exact changed-file set — decides that a PR carries nothing reviewable, and two distinct consequences follow from it.** The distinction is load-bearing and is the reason this is one spec rather than two:

- *"nothing here needs reviewing"* is a claim about the **diff**. True for both environments.
- *"no human needs to decide"* is a claim about the **consequence**. True for staging only.

Prod's gate was never a review gate. `promote-prod.yml` is `workflow_dispatch`, its diff is as mechanical as staging's, and what a human supplies at that merge is the *decision to promote*, not an inspection of two lines. ADR-046 D3 already says exactly this: staging is Continuous Deployment, prod is Continuous **Delivery**. So prod keeps its human merge and loses only the reviewer round-trip it never benefited from.

Observable behaviour after this spec:

1. A generated deploy or promote PR **is not reviewed by `pr-agent`**, in either environment, so it stops taking the single pending slot of the `pr-agent-nan-inference` concurrency group and displacing human PRs (#1203).
2. The same PR is admitted by `review-attestation` with verdict `exempt` and a reason string naming the signature it matched — distinguishable in the status description from `a review happened`.
3. A **staging** deploy PR merges without a human click once its required checks pass. A **prod** promote PR still waits for the operator's merge.
4. A PR that matches a signature **plus any other file** is refused by the gate and reads red, asking for a signature to be declared.

### Two mechanisms, deliberately not the same one

The gate matches the **exact changed-file set**. The reviewer matches the **branch prefix**. An earlier draft of this proposal called branch matching unsafe without qualification; that is wrong, and the repository had already worked out why — `pr-agent.yml` skips `release-please--` branches by name, with the reasoning stated in place:

> *"Branch-name matching was rejected for the attestation GATE because gaming the name would bypass review. Here it fails the other way: a branch named to match forfeits its review, and the gate then reports the PR unreviewed and goes red. Gaming it costs the gamer."*

The two ends of the same abuse point in opposite directions, so the same technique is a hole in one place and a protection in the other. The resulting asymmetry is benign both ways: a `deploy/*` branch carrying extra files is not reviewed **and** is refused by the gate (red, visible); a PR matching a signature from some other branch is reviewed anyway (wasted, harmless). A guard asserts the gate has not acquired a branch rule, so a future edit that "makes them consistent" fails rather than silently converting the protection into a hole.

This also replaced a heavier design: a preceding job resolving the file set through the toolkit, so both consumers shared one predicate. It would have added `poetry install` to **every** PR — 30–40s on all of them — to save time on 38%, and the shared predicate was the wrong shape rather than merely unnecessary.

### The mechanism already exists and is not being built here

`toolkit/features/review_attestation.py:222-238` already implements exempt-by-diff-signature, with exact set equality in both directions, and its own comment states the discipline this spec would otherwise have had to argue for:

```python
# Matched by DIFF SIGNATURE and nothing else — not by author (the tools that
# open such changes run under a human token, so an author rule never fires)
# and not by branch (any branch can be named to match).
```

Three signatures are declared today, all `release-please`. **The attestation half of this spec is therefore data, not code**: two new entries in `harness/review-attestation.json` under `exempt.signatures`. Measured on six real PRs (#1560, #1582, #1590, #1601, #1617 staging; #1618 prod), matching the file's own standard of naming the PRs a signature was observed on:

| Signature | Exact file set |
|---|---|
| staging deploy (single app) | `infra/config/values/staging.yaml`, `infra/k8s/overlays/staging/generated/deployments.yaml` |
| prod promote (single app) | `infra/config/values/prod.yaml`, `infra/k8s/overlays/prod/generated/deployments.yaml` |

Both are single-app shapes. A multi-app promotion would produce a different set and must be declared separately when one is first observed — the same lesson `release-please (api only)` records, where one signature was assumed sufficient and was not.

## Out of scope

- **Reopening ADR-046 D4 / Argo CD Image Updater.** Measured on the live hub today: `gcp1` has ~694 Mi free, so capacity is not the obstacle and D4 never claimed it was — it descoped on *"our CI already knows the tag it built"*, still true. Every write-back mode also meets the wall this spec routes around: git write-back to `master` is blocked by protection, a machine branch reintroduces lesson-256's drift, and `argocd` write-back mutates the Application spec, which `check-drift` (`argo_manager.py:104`, a whole-object `kubectl diff`) would report as permanent drift. D4's reopening trigger — auto-discovery of images we do **not** build — is untouched.
- **Environment branches / GitFlow.** `dev` would need the same protection to be safe, reproducing the wall; `check-config-drift.yml:54` validates staging and prod in one commit and would need redesigning; and it would strip pre-merge checks from human work, not only from bot work.
- **Fixing #1203 itself.** This removes ~38% of the contention for a queue whose depth is 1 and is GitHub's behaviour, not ours. A displaced run must still become observable rather than silently discarded; that stays #1203's.
- **Prod's human merge.** Untouched. `promote-prod.yml:107` refuses any `sha-*` tag and the promotion decision stays the operator's.

## Risks / open questions

- **[MUST RESOLVE BEFORE ANY CODE]** The auto-merge consequence (AC4) contradicts a standing global rule in the operator's `~/.claude/CLAUDE.md` (§9 of `pattern-git-workflow`), which forbids auto-merge in every repository at both the command and the repo-setting level. **That file is the operator's and is not edited on an agent's initiative.** The rule's stated purpose is narrower than its wording — §1 is titled *AI Integration Protocol* and its validation clause is *"The human engineer reviews PRs before merge"*, a gate against unreviewed **AI-authored** changes, which these diffs are not. Whether a shape-scoped exemption is faithful to that purpose is the operator's call. **AC1–AC3 stand on their own if the answer is no**, and are sequenced first for that reason.
- **A signature is a standing permission, and its negative case is the whole guard.** If the predicate ever admits a superset, this is a bypass with extra steps. Exact set equality already gives that property; what is missing is a test that *asserts* it. A committed negative test (signature files **plus** one workflow file → refused) is a deliverable, not a nicety.
- **Blast radius if `mlorentedev/web`'s CI is compromised.** An attacker who can publish an image and fire the dispatch reaches staging with no human in the path. Bounded to staging: prod requires a semver tag that this path cannot produce, plus the operator's merge. Accepted deliberately, recorded here so it is a decision rather than an oversight.
- **Suppressing the paid reviewers is the only genuinely new code**, and it is the half whose failure is silent: a condition that is too broad quietly stops reviewing real PRs. It must be expressed as the same predicate, evaluated from the same changed-file set, never as a branch-prefix or author condition.
- **Resolved during scoping, recorded so it is not re-investigated:** `review-attestation.json` has no schema for a bypass predicate and did not need one — `exempt.signatures` is the existing shape, and the gate reads `pr["files"]`, so no `workflow_run` context is involved and #1184's event-context loss does not apply here.

## Acceptance criteria

- [ ] **AC1** — Both signatures are declared in `harness/review-attestation.json` with the PR numbers each was measured on, and `toolkit/features/review_attestation.py` names no signature paths (the existing test that forbids reviewer identities in that module is extended, not forked).
- [ ] **AC2** — A real staging deploy PR and a real prod promote PR each reach `review-attestation` verdict `exempt`, with a status description naming the matched signature and distinguishable from `a review happened`. Verified on the status of a live PR of each kind, not on a unit test alone.
- [ ] **AC3** — A PR carrying a signature's files **plus one additional file** is refused by the attestation gate and by the reviewer-suppression condition. Verified by a committed test and by mutation (widen the predicate → the test goes red).
- [ ] **AC4a** — `pr-agent` does not run on a `deploy/*` or `promote/*` PR, so the pending inference slot stays available to human PRs. Verified by the absence of its `review` check on the next real deploy and promote PR after landing, and by a committed test asserting **both** prefixes (they are opened by two different workflows, so one can be dropped while a single-prefix test stays green).
- [ ] **AC4b** *(uncertain, and deliberately not promised)* — CodeRabbit and Codex do not run on these PRs. **Not yet established as achievable.** Both are external apps: this repository has no `.coderabbit.yaml` (its own comment reads `Configuration used: defaults`) and CodeRabbit's controls are `path_filters` (which excludes *files* from a review, not the review itself), title keywords, target branch, and labels — none is "the exact changed-file set", and title or label is precisely the claimable-token shape rejected for the gate. Codex is configured outside the repository entirely. **Deliverable here is the measurement, not the outcome:** determine what `path_filters` actually does to quota on a real PR, and report whether Codex can be scoped from the repo at all. Note this AC only affects *quota*; the latency win does not depend on it, because the `exempt` verdict already stops either reviewer from blocking the merge.
- [ ] **AC5** *(gated on the operator's decision in Risks)* — A staging deploy PR merges with no human click. Latency measured over the first five real deploy PRs after landing and reported against the 11h / 19h30m baseline as a number, not as "faster". Prod promote PRs still require the operator's merge, asserted by a PR of each kind observed after landing.

## References

- Bitácora board: `mlorentedev/kubelab#1619` (see the `issue:` frontmatter field)
- `docs/adr/adr-046-gitops-delivery-promotion-strategy.md` — D3 (staging is CD with no human gate), D4 (controller-free), and the 2026-06-15 amendment that introduced the gate this spec removes
- `docs/adr/adr-027-*` — the config-drift gate that makes the generated half of each diff non-reviewable by construction
- `#1203` — pr-agent concurrency queue depth 1; this spec reduces contention, does not close it
- `#1140` / `TOOL-021-review-attestation-and-reviewer-capacity` — the gate and its registry
- `00_meta/patterns/pattern-git-workflow.md` §1 and §9 — the AI Integration Protocol and the auto-merge prohibition whose scope AC5 depends on
