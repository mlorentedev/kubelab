---
tags: [spec, tasks, templates]
created: "2026-09-22"
---

# Tasks - OPS-023-retire-minio

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/ops-023-retire-minio`, worktree `~/Projects/kubelab-ops023-wt` ✓ 2026-09-23
- [x] Proposal written; R1 (data destruction) and R2 (order after #1780) resolved by the operator ✓ 2026-09-23
- [x] Full-repo inventory: 135 files, grouped by category, in `verification.md` ✓ 2026-09-23
- [x] #1780 (SSOT-017) merged, and this branch rebased on it (R2). **No implementation before this.** ✓ 2026-09-24
- [x] BACKUP-049 (#1171) closed or re-scoped by the operator. Its draft spec instruments the CronJob this spec deletes. ✓ 2026-09-24 (closed as superseded)

## Implementation

> Three PRs, in this order. Each one is independently green, and each leaves nothing half-removed that a later PR has to rescue.
> The order inside PR 1 follows a rule: **silence the monitors first, then remove the service, then remove the names.** Removing a service while its monitors still run pages for a planned change. Removing DNS first breaks a running service.

### PR 1: the K8s runtime and everything that points at it

- [x] [AC5] Write the guard first and show it red: a test fails if a live file references MinIO. Live means outside ADRs, lessons, archived specs, audits, CHANGELOG, and this spec. It lands as `xfail(strict=True)` so PR 1 and PR 2 stay green; PR 3 removes the marker, and `strict` makes an early pass fail, forcing that removal. The red run is recorded in `verification.md`.
- [x] [AC1] Remove the 3 Uptime Kuma monitors from `infra/config/uptime-kuma/monitors.json`: `services-data-minio-prod`, `services-data-minio-console-prod` and `staging-web-minio-staging`. Remove the homepage tiles via `toolkit/scripts/sync_homepage_config.py`, then regenerate.
- [x] [AC1] Delete the `pvc-backup` CronJob (`overlays/prod/backup.yaml`) and `make backup-pvc`. Mark ADR-024's CronJob as retired.
- [x] [AC1] Delete `base/services/minio.yaml`, meaning the PVC, ConfigMap, Deployment, Service and both IngressRoutes. Also delete its `kustomization.yaml` entry and image pin and the prod `patches.yaml` block. `renovate.json`'s pin and the `SERVICES_DATA` special case in `generator_traefik.py` go in PR 3, with the SSOT block they read.
- [x] [AC3] Delete the `minio` client from `oidc_clients` and regenerate `oidc-clients.yml`. Delete the `console.minio` / `minio` domain rules in both Authelia `configuration.yml` files.
- [x] [AC4] Retire the SOPS keys. This shrinks the orphan baseline (#1513); it never adds to it. Remove the catalog entries and `toolkit secrets unset` the same keys in every vault in one change, so no orphan ever exists. Order: remove the client from `oidc_clients`, run `toolkit sync oidc` for both envs, and only then unset the hash. The keys:
  - `apps.services.data.minio.oidc_client_secret`;
  - `authelia.oidc_client_secret_minio_hash`.
  `root_password` and the `root_user` baseline entry move to PR 3: the Beelink and the dev stack read them until then.
  Also remove them from `SECRET_CATALOG`, `k8s_secrets.py` (`minio-secrets`, `_IDENTITY_BACKED`) and `credentials.py` (the minting and `CREDENTIAL_SERVICE_MAP`). Coordinate with #1777, which rewrites the same minting code.
- [x] [AC1] SSOT, K8s side only: remove the per-env `domain`/`console_domain` overrides in `staging.yaml` and `prod.yaml`, which only K8s routes read. **The `apps.services.data.minio` block in `common.yaml`, `dev.yaml` and the `root_password` key stay until PR 3.** `provision-bee.yml` (PR 2) and the dev Compose stack (PR 3) still read them, so removing them here would break `make provision NODE=bee` between merges. Reordered 2026-09-24.
- [x] [AC1] Tests: update the suites that assert MinIO exists (the inventory's category 5) so they assert its absence or drop the case. **Keep** `test_secrets_orphan_audit.py`'s worked example on a different key.
- [x] [AC1] Remove `minio` and `console.minio` from `infra/terraform/dns/services.json` and from the CoreDNS `Corefile.j2` split-DNS hosts. The Terraform plan must show exactly those records destroyed and nothing else.
- [ ] [AC1] Delete the `minio-secrets` Secret in both envs. `apply-secrets` creates it outside git, so Argo CD never prunes it, and removing the code leaves the root password in etcd (the TOOL-025 shape). Decided 2026-09-24: `RETIRED_SECRETS` in `k8s_secrets.py`, which every `make apply-secrets` deletes with `--ignore-not-found` (`tests/test_retired_secrets.py`). Record the run for each env in `verification.md`.
- [ ] [AC1] **Before merge:** sync the Uptime Kuma monitors to the RPi3, so the prune does not page for a planned change.
- [ ] [AC1] Staging validation: `targetRevision` on the branch, then read the before and after state with `kubectl get deploy,svc,pvc,cronjob,ingressroute | grep -i minio`. Point `targetRevision` back after merge.
- [ ] [AC1] [AC6] Prod after merge: Argo CD prunes, and the before/after `kubectl get` output is recorded. `make backup-coverage` stays fully covered. An authorization request for `client_id=minio` returns `invalid_client` in both envs (AC3).

### PR 2: the Beelink

- [ ] [AC2] In `beelink_services`, the role that still owns the node, add a teardown on the pattern of the act_runner removal:
  - the container stops and is removed from the compose project;
  - `/opt/minio/data` is removed;
  - the firewall ports in `provision-bee.yml` are closed;
  - the `minio_*` vars and the compose block are deleted.
  Run `make provision NODE=bee ENV=prod` twice; the second run must report `changed=0`.
- [ ] [AC2] Update the Headscale ACL comment and the `VPNACL-001` draft's `tag:hermes → MinIO` rule as a note on that spec. The rule's target no longer exists.

### PR 3: the local dev stack, docs, and the guard going green

- [ ] [AC1] SSOT and generated artifacts, moved here from PR 1 (2026-09-24):
  - remove `apps.services.data.minio.*` from `common` and `dev.yaml`;
  - remove MinIO from `platform_manifest.py` and regenerate `platform.json`;
  - remove it from `sync_k8s_images.py`'s key list and `renovate.json`;
  - retire `apps.services.data.minio.root_password` and delete the `root_user` baseline line (AC4).

- [ ] [AC5] Delete `infra/stacks/services/data/minio/` and remove its entries from the stack README and the Makefile dev targets (cert hosts, `services up` lists, login hint).
- [ ] [AC5] Docs that describe current state (inventory category 8): delete `docs/runbooks/pvc-backup-restore.md`, and rewrite the rest to drop MinIO. Include `docs/runbooks/runbook-disaster-recovery.md`, which predates restic. Historical ADRs get a retirement note, not a rewrite: ADR-061 D4 records the decision, and ADR-023, 024 and 028 point to it. Update CLAUDE.md and README.
- [ ] [AC5] The guard from PR 1 turns green. Mutation proof: re-adding one live reference turns it red.

## Closing

- [ ] #972 closed by PR 3 (`Closes #972`); #1784 is already closed as a duplicate.
- [ ] `verification.md` holds, for each environment and the Beelink, the before and after state, the Terraform plan, the `changed=0` run and the `backup-coverage` output.
- [ ] Independent adversarial review (`review.md`) before `/spec archive`.

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/OPS-023-retire-minio/features.json`):

```json
[
  {
    "id": "OPS-023-retire-minio-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
