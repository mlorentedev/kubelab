---
tags: [spec, tasks, templates]
created: "2026-09-22"
---

# Tasks - SSOT-017-oidc-client-ssot

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/ssot-017-oidc-client-ssot`, worktree `~/Projects/kubelab-ssot017-wt` ✓ 2026-09-22
- [x] `proposal.md` complete, with testable acceptance criteria ✓ 2026-09-22
- [x] Open questions resolved: R6 (`argocd.domain`) and names, 2026-09-22. R1 and R5 are verified during implementation by the tasks tagged below ✓ 2026-09-22

## Implementation

> Commit before every red-proof mutation (CLAUDE.md, "Commit before mutating").

- [x] [AC1] Write a failing test: for staging and prod, the client set and every non-secret field in the committed Authelia config equal what the SSOT derives. It needs no SOPS. It is red against today's files: the ids differ, `gitea` and `argocd` are absent from the SSOT, and `kubelab-oidc` has no registration. ✓ 2026-09-22
- [x] [P] [AC4] Write a failing test: an SSOT client without `token_endpoint_auth_method` or `authorization_policy` fails generation, and the error names the client. ✓ 2026-09-22
- [x] [AC1] [AC4] Extend the SSOT schema in `common.yaml`:
  - align the ids (`grafana`, `minio`, `gitea`, `argocd`, `vikunja-oidc`);
  - drop `kubelab-oidc`;
  - add `envs`, `token_endpoint_auth_method`, `authorization_policy`, `consent_mode` and `redirect` (domain reference plus callback path) to each client;
  - add `argocd.domain`.
  Every value is copied from the live prod file, not typed from memory (R1). ✓ 2026-09-22
- [x] [P] [AC6] Write a failing test: the K8s generator and the Compose renderer (`generator_authelia.py`) resolve the same `client_id` set per environment through one shared resolver. It is red because the Compose renderer derives digest keys itself (`:138`). ✓ 2026-09-22
- [x] [AC6] Measure R8: is any dev Compose service configured as an Authelia OIDC client? Record the answer and set `dev` in `envs` accordingly. ✓ 2026-09-22
- [x] [AC1] [AC4] [AC6] Implement the shared resolver: env filter, host from the domain reference, and the digest-key convention from `generator_authelia.py:138` (proposal What). `public: false` is fixed there. ✓ 2026-09-22
- [x] [AC1] [AC4] Implement the K8s generator on top of the resolver, and move the Compose renderer onto it as well. It renders `oidc-clients.yml` per environment from the SSOT and the stored SOPS digests (R7). It fails on a missing required field and on a missing digest. The tests turn green. ✓ 2026-09-22
- [x] [AC2] Split the config:
  - remove `clients:` from both `configuration.yml` files;
  - add `oidc-clients.yml` to the `authelia-config` configMapGenerator in base and in the prod overlay (`behavior: replace` carries both files);
  - mount both files and name them via `--config` / `X_AUTHELIA_CONFIG` (R4). ✓ 2026-09-22
- [x] [AC2] Verify the emitted objects with `kubectl kustomize infra/k8s/overlays/{staging,prod}`. The ConfigMap holds both files. A change to `oidc-clients.yml` alone changes the name hash, which means the Authelia pod rolls. Evidence goes to `verification.md`. ✓ 2026-09-22
- [x] [AC3] Rewire the writers:
  - `toolkit sync oidc` and `sync all` call the generator;
  - `_get_oidc_output_files` returns the generated files;
  - `make credentials-generate` inherits this through `sync all`;
  - delete `toolkit/scripts/sync_oidc_hashes.py` and replace `tests/test_sync_oidc_hashes.py` with the generator's tests;
  - `--check` reports drift when a stored digest changed but the file was not regenerated. That last point is shown red first. ✓ 2026-09-22
- [x] [AC1] Re-grep for consumers of every removed or renamed id (`kubelab-oidc`, `grafana-oidc`, `minio-oidc`) and of staging `argocd` before the first apply (R5). Record the result. ✓ 2026-09-22
- [ ] [AC5] Staging validation:
  - repoint the staging Application `targetRevision` to the branch (R3, lesson-256);
  - `make deploy-k8s ENV=staging`;
  - SSO login to grafana, minio and vikunja-oidc on staging;
  - an authorization request with `client_id=argocd` against staging Authelia returns an OIDC client error, while the same request against prod redirects to login. The discovery document does not list clients, so it cannot show this;
  - repoint to `master` after merge.
- [ ] [AC5] Prod: after merge, Argo CD syncs prod. SSO login to grafana, minio, gitea, argocd and vikunja-oidc. Measure vikunja-oidc's token auth method from Authelia's logs or a token exchange, and correct its "unverified" comment. If any login fails, revert the merge, never patch by hand (R2).

## Closing

- [x] Amendment note in ADR-040 §1: the target state is built, and it reads stored digests, not recomputed ones (R7). ✓ 2026-09-22
- [x] CLAUDE.md gotchas that name `sync-oidc-hashes` as the writer of `configuration.yml` are updated. So is the "rotating is not landing" note: the command now writes `oidc-clients.yml`. ✓ 2026-09-22
- [x] File a ticket: the Argo CD Helm values hardcode `argo.kubelab.live` instead of reading `argocd.domain` (R6). Filed as #1782 (SSOT-027), widened to every consumer-side literal `client_id`. ✓ 2026-09-22
- [ ] Every acceptance criterion is covered by at least one test or recorded measurement, with a matching `features.json` entry.
- [ ] `make test` green, lint green, no unrelated changes in the diff.
- [ ] `verification.md` filled in.
- [ ] PR #1780 merges with **`Refs #1332`, never `Closes`**. The spec gate refuses a PR that closes a spec's issue without archiving it, and archiving needs AC5-prod, which can only be measured after merge, because Argo CD syncs prod from master. Record the `--force-no-gate` scaffold and the reason.
- [ ] Follow-up docs PR after the prod logins: prod AC5 evidence, then the adversarial review (`review.md`), then `/spec archive`. It carries `Closes #1332`.
- [ ] Independent adversarial review (`review.md`) before `/spec archive`.

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/SSOT-017-oidc-client-ssot/features.json`):

```json
[
  {
    "id": "SSOT-017-oidc-client-ssot-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
