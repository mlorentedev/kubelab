---
tags: [spec, tasks, templates]
created: "2026-06-26"
---

# Tasks - DELIVERY-003-errors-tag-automation

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.

## Setup

- [x] Branch created from master: `feat/DELIVERY-003-errors-tag-automation`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions" (both RESOLVED)

## Implementation

> TDD order, one focused commit each. Part A = single SSOT for K3s (AC1/AC3/AC4). Part B = auto-pin on release (AC2/AC5).

### Part A — `errors` on the sync lane (single SSOT)

- [x] Write failing test (`tests/test_sync_k8s_images.py`): the synced `images:` block contains `docker.io/mlorentedev/kubelab-errors` with `newTag` == `edge.errors.version` from common.yaml, sourced from the structured `edge.errors` keys (registry + image_name + version), no network.
- [x] Implement: add a structured-source path in `sync_k8s_images.py` that emits `errors` from `{registry}/{edge.errors.image_name}:{edge.errors.version}`; refactor `build_images_block` if needed (no dup with the third-party path).
- [x] Remove the hand-edited `kubelab-errors` `newTag` from the custom-apps group in `infra/k8s/base/kustomization.yaml`; run `make sync-k8s-images` so it re-appears in the synced block.
- [x] Verify the drift gate is green (`generated == committed`) after the sync.

### Part B — auto-pin `errors` on release (no manual edit)

- [x] Write failing test (`tests/test_promotion.py`): `promote(env, "errors", X.Y.Z)` verifies the registry tag exists, writes `edge.errors.version` in `common.yaml`, and triggers the image sync (mock the sync + registry). Rejects a non-existent tag (AC5).
- [x] Implement: route `errors` in `promotion.promote` to an edge path (write `edge.errors.version` in common.yaml + run the image sync) instead of the per-env overlay path; keep platform apps unchanged. CLI `deployment promote --app errors` accepts it (env optional/ignored for edge — single SSOT).
- [x] `release.yml`: add a job on `errors_release_created` that runs `toolkit deployment promote --app errors --version <errors_version>`, then opens a PR with the bumped `common.yaml` + synced `kustomization.yaml` (mirrors `staging-deploy.yml` open-pr). `publish-errors` (rebuild) stays.

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [x] Type checks pass (`make type`)
- [x] Lint passes (`make lint`)
- [x] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [ ] PR opened referencing this spec folder
- [ ] On merge: `git mv specs/DELIVERY-003-errors-tag-automation specs/archive/...`; #776 closes

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/DELIVERY-003-errors-tag-automation/features.json`):

```json
[
  {
    "id": "DELIVERY-003-errors-tag-automation-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
