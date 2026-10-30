---
tags: [spec, tasks]
created: "2026-10-26"
---

# Tasks - VPN-ACL-006-headscale-upgrade

Provisional TDD plan, not permission to implement. `[ACn]` maps a step to the
proposal; `[P]` means no dependency on another unchecked implementation step.
Each red/test/green action is separate. Commit boundaries are reviewed in Setup,
not inferred from this entire document being one delivery.

## Setup

- [x] Verify open issue #248; operator selects planning only.
- [x] Reuse the external prepared worktree and fast-forward to `e1d9be29`.
- [x] Record the explicitly approved planning-only WIP exception in proposal.
- [x] Resolve G1/G7, review G3/G4 and freeze acceptance/atomic PR boundaries.
  ✓ 2026-10-29: operator accepted the three amendments and renewed the WIP
  exception; G7 closed by #2820.
- [x] Revalidate branch/base/lease before code. ✓ 2026-10-29: the spec moved
  to `docs/vpn-acl-006-headscale-upgrade-spec` from `origin/master`; the
  inherited `feature/isolated-headscale-instance` name is retired.
- [ ] Resolve compatibility gate G2 and production gates G5/G6/G8 before
  rollout. Never infer these approvals from the planning exception.
- [x] Run `/spec check VPN-ACL-006-headscale-upgrade` after contract approval.
  ✓ 2026-10-30: re-run on the frozen contract (amendments included). PASS,
  deterministic `[ACn]` path: 7 criteria, 31 Implementation tasks, none
  uncovered, no orphan task.

## Implementation

### 1. Eligibility before mutation

- [x] [P] [AC1] Add synthetic eligibility cases in proposed
  `tests/test_headscale_upgrade.py`: old/unknown native and embedded client
  versions, absent approval, invalid version transition, unverified image,
  required nodes whose key is expired yet online, and required nodes whose
  given name carries the pre-v0.29 random suffix. ✓ 2026-10-30 (#2823)
- [x] [AC1] Run `python -m pytest -o addopts= tests\test_headscale_upgrade.py -k eligibility -q`.
  Expected RED: the preflight behavior is not implemented. ✓ 2026-10-30:
  collection error, `ModuleNotFoundError`.
- [x] [AC1] Add only the tested eligibility behavior to proposed
  `toolkit/features/headscale_upgrade.py`, using existing SSOT/config helpers.
  ✓ 2026-10-30: a pure function of handed facts; collecting them is task 6.
- [x] [AC1] Repeat the same command; require GREEN and assert the fake runner
  observed zero mutation commands for every refusal. ✓ 2026-10-30: 39 passed;
  the module imports nothing that can reach a process, a file or the network.

### 2. Version/configuration compatibility

- [ ] [AC2] Add render/consumer cases to `tests/test_headscale_upgrade.py`,
  `tests/test_headscale_role.py` and `tests/test_headscale_nodes.py` for the
  selected image, removed config keys and changed duplicate-name forms.
- [ ] [AC2] Run `python -m pytest -o addopts= tests\test_headscale_upgrade.py tests\test_headscale_role.py tests\test_headscale_nodes.py -q`.
  Expected RED on new compatibility assertions.
- [ ] [AC2] Make the minimal compatibility edits in
  `infra/config/values/common.yaml`,
  `infra/ansible/roles/headscale/templates/config.yaml.j2` and, only where
  the regression proves necessary, `toolkit/features/headscale_nodes.py`:
  rename `ephemeral_node_inactivity_timeout` to
  `node.ephemeral.inactivity_timeout`, set `trusted_proxies` to the value the
  drill proves, and pin the image by OCI index digest.
  Do not apply these changes to production.
- [ ] [AC2] Repeat the same command; require GREEN. Confirm the candidate
  registry manifest includes Linux ARM64 and record the verified image digest.

### 3. Preserve traffic across wildcard changes

- [ ] [AC3] Add required-subnet and no-unintended-widening assertions to
  `tests/test_headscale_upgrade.py` using synthetic identities and addresses.
- [ ] [AC3] Run `python -m pytest -o addopts= tests\test_headscale_upgrade.py -k preserved -q`.
  Expected RED where old wildcard semantics lose a required route.
- [ ] [AC3] Adapt `infra/ansible/roles/headscale/templates/policy.hujson.j2`
  and `toolkit/scripts/headscale_probe.py` only to preserve approved flows
  from SSOT: add `lan-rpi4:*` to rule 1's destinations (G4). Reuse
  `toolkit/scripts/render_headscale_policy.py`; do not
  introduce separately editable address lists.
- [ ] [AC3] Repeat the same command; require GREEN. Add actual candidate-version
  traffic checks in the disposable harness below; mocks alone do not satisfy AC3.

### 4. Backup, migration and restoration

- [ ] [AC4] Add corrupt/missing snapshot and migration/restore sequencing tests
  to `tests/test_headscale_upgrade.py` and `tests/test_headscale_drill.py`.
- [ ] [AC4] Run `python -m pytest -o addopts= tests\test_headscale_upgrade.py tests\test_headscale_drill.py -q`.
  Expected RED for the new full-version-restore behavior.
- [ ] [AC4] Reuse `toolkit/features/headscale_drill.py` and existing lifecycle
  work under #433. Capture consistent stopped state, configuration, keys,
  image pin and SQLite state before migration; keep the snapshot immutable.
  Restore to a separate writable copy, never downgrade a migrated database.
- [ ] [AC4] Repeat the same command; require GREEN for refusal, identity
  preservation and correct restore ordering. Never use real secrets in tests.

### 5. Real candidate-version assertions

- [ ] [AC4] Add a synthetic populated v0.28 database fixture in proposed
  `tests/integration/test_headscale_upgrade.py`; use generated disposable
  keys, never copied production state.
- [ ] [AC4] Add a failing migration assertion in the same file for node/user
  and server-identity continuity on v0.29.6.
- [ ] [AC4] Add a failing restoration assertion using an untouched pre-upgrade
  snapshot and v0.28 image, not the migrated database.
- [ ] [AC3] Add disposable userspace-client probes for the required subnet
  and private-flow cases, with healthy controls for negative assertions.
- [ ] [AC5] Add populated-state positive/failing native policy tests and
  rejected-write/reload assertions.
- [ ] [AC3] [AC4] [AC5] Add the fail-closed `headscale-upgrade-drill` target
  in `Makefile` to run the explicit disposable test set. Missing prerequisites
  or a skipped required case must return nonzero.
- [ ] [AC3] [AC4] [AC5] Run `make headscale-upgrade-drill` from Git Bash/WSL
  on Windows, or a supported Linux test host. Expected RED on deliberate
  migration, route or rejected-policy faults; missing prerequisites and
  skipped required cases must return nonzero, never a success-shaped skip.
- [ ] [AC5] Reuse the effective-policy acceptance work under #2190 and
  restoration work under #2184. Test both a policy write and SIGHUP rejection,
  verify the last accepted policy, and distinguish it from the on-disk file.
  Verify v0.29.6 native tests actually evaluate against populated state.
- [ ] [AC3] [AC4] [AC5] Repeat the drill without injected faults; require
  preserved traffic, executed positive/negative policy tests and a working
  full restore. The harness must not call production, SOPS, restic or live SSH.

### 6. Safe execution and convergence contract

- [ ] [AC6] [AC7] Add unit cases in `tests/test_headscale_upgrade.py` for
  read-only default, explicit apply approval, post-start checks, second-run
  convergence, redacted errors and resource cleanup on every failure.
- [ ] [AC6] [AC7] Run `python -m pytest -o addopts= tests\test_headscale_upgrade.py -k "rollout or safety" -q`.
  Expected RED on missing guards or unintended repeated mutations.
- [ ] [AC6] [AC7] Wire the reviewed behavior through existing toolkit CLI
  conventions and `infra/ansible/roles/headscale/tasks/main.yml`. Improve
  acceptance beyond the existing version-only Docker healthcheck without
  inventing an unsupported HTTP health endpoint.
- [ ] [AC6] [AC7] Repeat the same command; require GREEN. Exercise two applies
  in the disposable harness and assert no second migration or restart.
- [ ] [AC7] Document preflight, protected backup, stop/start, validation and
  full-state restore in `docs/runbooks/headscale-setup.md`, linking the
  owning backup runbook rather than copying secret-handling procedures.
- [ ] [AC1] [AC4] [AC6] [AC7] After separate explicit production approval,
  execute only the reviewed IaC path in the scheduled window and collect
  redacted acceptance receipts. No live command is authorized by this task list.

## Closing

- [ ] All seven criteria have real executed evidence, not only task coverage.
- [ ] Run `make check-headscale-policy` against the selected candidate pin;
  this existing syntax gate alone does not satisfy AC5.
- [ ] Run targeted unit/integration checks, then repository lint/type checks
  and the required regression suite before publication.
- [ ] Fill `verification.md`; retain missing checks and failures explicitly.
- [ ] Only the harness may promote `features.json` entries to `passing`
  after executing their non-vacuous commands and capturing evidence.
- [ ] Independent review before archival; disposition all PR feedback.
- [ ] Do not close #248 from this draft or claim restricted-segment acceptance.
