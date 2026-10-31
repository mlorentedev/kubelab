---
id: "DELIVERY-004-exempt-generated-deploy-prs"
status: implementing # draft | implementing | verifying | archived
type: spec
created: "2026-09-04"
issue: "mlorentedev/kubelab#1619"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# DELIVERY-004-exempt-generated-deploy-prs

> Rewritten 2026-10-21 against the operator decision of 2026-10-20 on #1619, which
> approves the unattended merge of **staging** deploy PRs under the "diff nobody
> wrote" exception, provided its four conditions (a)-(d) are built and proven here.
> The 2026-09-04 draft is in git history; what it planned and what has since landed
> is recorded under "Already on master".

## Why

Generated deploy PRs carry nothing a reviewer can act on, yet they consumed 23 of 60
reviewed PRs (38%), received vendor capacity notices instead of reviews, displaced
human PRs from pr-agent's single pending slot (#1203), and waited 11h (#1560) and
19h30m (#1590) for a click that ADR-046 D3 says staging does not need ("No human
gate"). The issue body has the measurements.

## Already on master (not claimed by this spec)

- `harness/review-attestation.json` `exempt.signatures` declares `staging deploy
  (single app)` and `prod promote (single app)` as exact changed-file sets.
- `.github/workflows/pr-agent.yml:154-161` skips `deploy/` and `promote/` head
  branches. This is the forfeit direction: a branch named to match loses its review.

### The gap this leaves

The staging exemption is keyed on the **file set only**. Any PR touching just
`values/staging.yaml` and the generated overlay is exempt from review, whatever it
changes in them: resource limits, env vars, a domain, an image repository. That is a
grant, and it is wider than the class it was written for. The prod signature has the
same shape; it is #1741's to tighten (prod is out of bounds here), and the gap is
recorded there rather than fixed here.

## What

One predicate, `deploy-shape`, decides that a PR is a **mechanical staging deploy**:

1. The changed-file set is exactly `infra/config/values/staging.yaml` and
   `infra/k8s/overlays/staging/generated/deployments.yaml`, both `modified`.
2. Between the merge base and the head sha, `values/staging.yaml` differs in exactly
   one leaf, `apps.platform.<app>.version`, where `<app>` is an entry of
   `infra/config/products.yaml`, and the new value matches `^sha-[0-9a-f]{7,40}$`.
3. The overlay differs only in `image` leaves, each going from `<repo>:<old>` to
   `<repo>:<new>` with the same `<repo>`, where `<old>`/`<new>` are the values change,
   and there is at least one such leaf.
4. Provenance, keyed on the registry entry: the tag's hex resolves to exactly one
   commit on the default branch of the product's repository (`repository` for a
   `github` product, this repository for `in-tree`). This is what "equals the
   dispatched sha" can mean to a check that sees `pull_request` and never the
   dispatch: the receiver's own resolve step, re-run on the output.

The predicate is computed by `toolkit/features/deploy_shape.py` from **master's** code,
reading the PR only through the API. Its three outcomes are distinct:

| Outcome | Meaning | Published as |
|---|---|---|
| `mechanical` | all four hold at the verified head sha | commit status `deploy-shape`, `success` |
| `not-mechanical` | evaluated, and some condition does not hold | `success`, the verdict in the description (the PR takes the normal review path) |
| `unknown` | anything could not be read or parsed | `failure` (fails closed) |

A contract-change deploy PR (it also carries `contracts/<app>.yaml` and contract-owned
values) reads `not-mechanical`, never red: its diff is reviewable, and the receiver's
PR body says so. Since pr-agent forfeits `deploy/` by name, such a PR arrives with no
review and the attestation gate keeps it red until someone types `/review`. That is
the forfeit asymmetry working as designed.

### Consumers recompute; they never read the check's conclusion

A same-repository PR can add a workflow that posts a status named `deploy-shape`
with `GITHUB_TOKEN`. So the check is the **visible** assertion, and every consumer
that *grants* something recomputes the predicate itself from master's code at the
head sha it verified:

- `review-attestation` replaces the file-only staging signature with the predicate.
- The merge job (PR 3) recomputes it, then merges with
  `gh pr merge --squash --match-head-commit <verified sha>`.

### Declared class

`harness/review-attestation.json` gains a `mechanical` block naming the class, its
env (`staging` only), its file set, the version path and the tag pattern. The module
reads them from there; `toolkit/features/review_attestation.py` and
`toolkit/features/deploy_shape.py` name no paths (the existing "no policy in the
module" test is extended). Branch prefix and author grant nothing anywhere.

### Paid reviewers

pr-agent already forfeits. CodeRabbit and Codex are external apps: CodeRabbit has no
`.coderabbit.yaml` here (adding one may reset UI-set keys to defaults) and Codex is not
configurable from the repository. For them the deliverable is a measurement, not a
promise: the exemption already stops either from blocking the merge, so only their
quota is at stake.

### Merge identity

`RELEASE_PLEASE_TOKEN`, the PAT the receiver already uses to open the PR. A merge with
`GITHUB_TOKEN` starts no `push` workflow, and these must run after a staging deploy
lands on master: `check-config-drift`, `ci`, `ci-cleanup` (paths include
`values/staging.yaml`), `release` (release-please) and `repo-hygiene`.
(`staging-deploy` is `apps/**` only.) Swapping the PAT for a GitHub App is the
follow-up recorded on mlorentedev/dotfiles#2836 (SEC-017).

## Out of scope

- `promote-prod.yml`, the prod signature, and #1741 (DELIVERY-007).
- The receiver (`product-image-receiver.yml`), owned by IDP-042.
- Reopening ADR-046 D4, environment branches, and #1203 itself (the issue body says why).

## Risks / open questions

- **A neutral check-run must satisfy a required check.** GitHub documents `success`,
  `neutral` and `skipped` as passing. Verified on a real PR before the context is added
  to protection, because a required context that never passes blocks every merge.
  Resolved by DELIVERY-011 (#2714): the neutral check-run did pass, but only where
  GitHub filed it under a suite that never re-ran. It files an API-created check-run
  under the first github-actions suite on the sha, and once that workflow runs again
  protection reads the context as "Expected". The verdict is now a commit status.
- **Fork PRs** get a read-only token and cannot publish the check, the same as
  `review-attestation` today. Accepted; noted so it is a decision.
- **Compromised product CI** reaches staging with no human. Bounded: staging only,
  provenance requires a merged commit on the product's default branch, and prod
  needs a semver tag and the operator's merge.
- **Back-to-back merges and post-deploy verification** (#2584): the switch must not
  flip onto a verifier that reads HEAD once.

## Acceptance criteria

The operator's (a)-(d) are the contract; each AC names which it proves.

- [ ] **AC1 (a)** — `deploy-shape` runs on every PR to master from master's code and
  publishes the status as above: `success` with the verdict in its description, or
  `failure`. Unit tests cover each condition's negative case; it is `mechanical` on
  #2576 and #2581 (version-only) and `not-mechanical` on a contract-change shape and on
  a human PR. Any read or parse failure is `failure`.
- [ ] **AC2 (c)** — The class is declared in `harness/review-attestation.json`;
  neither module names its paths. `review-attestation` exempts a staging deploy only when
  the recomputed predicate is `mechanical` at the head sha it attests; the file-only
  staging signature is removed. A PR with the right two files and any other change in
  them is not exempt.
- [ ] **AC3 (a)** — `deploy-shape` is added to `ci.branch_protection` `required_contexts`
  after a not-mechanical run is observed passing protection on a real PR; the live reconcile is
  the operator's.
- [ ] **AC4 (c)** — Widening tests: committed tests go red if the declared file set, the
  version path, the tag pattern or the env widen, or if the merging job's `if:` or merge
  command changes. Each proven by `make mutate`.
- [ ] **AC5 (d)** — A test asserts the merging job cannot act on `values/prod.yaml`, the
  prod overlay, or a semver tag: the predicate refuses them, and the declaration admits
  only `staging`.
- [ ] **AC6 (b)** — The merge job (PR 3) recomputes the predicate, merges with
  `gh pr merge --squash --match-head-commit <sha>` under `RELEASE_PLEASE_TOKEN`, and is
  behind a committed switch that defaults to off. `allow_auto_merge` stays `false`
  (`tests/test_no_auto_merge.py`).
- [ ] **AC7** — The switch flips in its own PR only after: GITOPS-003's PR 2
  (`deploy-verify.yml` on `status` + schedule, with the `argocd/kubelab-staging` status)
  and #2584 have landed, and several green assert-only runs on real deploy PRs are
  linked on #1619. Rollback is reverting that PR. State on 2026-10-21: #2584 closed by
  #2591 (`verify-product` exits 4 when a later merge supersedes the tag); `toolkit infra
  argo wait-status` landed with #2590. #2594 merged (`a1bfce39`) and is deployed to the hub: Argo CD
  posts `argocd/<app>` commit statuses (`argocd/kubelab-prod: success` seen on master
  `45702f5e`). Still missing: `deploy-verify.yml` (GITOPS-003 PR 2b).
- [ ] **AC8** — Measurement, not promise: whether CodeRabbit and Codex still spend quota
  on deploy PRs, reported on #1619.

## References

- #1619 (operator decision 2026-10-20), #1741, #1478 / GITOPS-003, #2584, #1203
- ADR-046 D3/D6, ADR-027 (config drift), ADR-067 (product contract)
- mlorentedev/dotfiles#2836 (SEC-017, the App identity)
