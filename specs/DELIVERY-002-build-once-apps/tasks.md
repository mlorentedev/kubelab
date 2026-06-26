---
tags: [spec, tasks, delivery, ci-cd]
created: "2026-06-26"
---

# Tasks - DELIVERY-002-build-once-apps

> TDD order. One task = one focused commit. Tick as you go. Spec frozen on entry to `implementing`.
> Two PRs (atomic): **PR-1** = ADR-056 + this spec (decision, no code). **PR-2** = the build-once implementation.

## Setup

- [x] Branch created from master: `docs/adr-056-build-once-delivery` (PR-1: ADR + spec) ✓ 2026-06-26
- [x] `proposal.md` complete; acceptance criteria testable ✓ 2026-06-26
- [x] **ADR-056 ratified by the operator** — "which digest to re-tag" resolved: **B1 (staging-pinned sha)** ✓ 2026-06-26

## Implementation (PR-2 — after ADR ratified)

> TDD where the surface allows. The toolkit resolver is unit-testable; the workflow re-tag is verified by digest equality.

- [ ] Write failing unit test: a toolkit helper resolves the staging-pinned `sha-<short>` for `api` from `infra/config/values/staging.yaml` (`apps.platform.api.version`), no network. Asserts SSOT-sourced, errors on a non-sha pin.
- [ ] Implement `toolkit deployment image-tag --env staging --app <app>` (prints the pinned tag) to make it pass.
- [ ] Refactor: extract the values-loading shared with `deployment promote` (no dup).
- [ ] `release.yml`: replace `publish-api` (which calls `ci-publish.yml` → rebuild) with a **re-tag job** — resolve the staging sha via the toolkit, `docker login`, `docker buildx imagetools create -t <img>:<version> <img>:<sha>`, then `imagetools inspect` to log the resolved digest. **`publish-errors` is left unchanged** (errors out of scope — edge infra, ADR-056 *Alternatives*).
- [ ] Guard the prune race: `ci-cleanup.yml` must not prune a `sha-*` tag referenced by a committed overlay (or document that re-tag precedes the prune window). Add a test/assertion if code-guarded.
- [ ] Update `docs/runbooks/gitops-delivery-promotion.md`: the promotion sequence is now build-once (no manual candidate-semver validation step — parity is structural).

## Closing

- [ ] Every acceptance criterion covered by a test/smoke check (digest-equality assertion for the re-tag)
- [ ] `features.json` emitted (one feature per acceptance criterion; `state: pending` until the harness runs them)
- [ ] Type checks pass (`make type`)
- [ ] Lint passes (`make lint`)
- [ ] No unrelated changes (no CalVer `ci-release.yml` edits — that is a separate ticket)
- [ ] `verification.md` filled (digest-equality evidence: `<app>:X.Y.Z` == `:sha-<short>`)
- [ ] PR opened referencing this spec folder
- [ ] On merge: `git mv specs/DELIVERY-002-build-once-apps specs/archive/...`; #679 closes (built-in workflow → Done)

## Machine-readable features

Emit a sibling `features.json` once acceptance is frozen (id, behavior, verification, state, evidence).
The agent CANNOT set `state: passing` — only the harness, after running `verification` with exit 0.
