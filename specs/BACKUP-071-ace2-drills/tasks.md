---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-071-ace2-drills

> TDD order. One task = one focused commit. `[P]` = no dependency on another unchecked task. `[AC<n>]` = serves acceptance criterion n.

## Setup

- [ ] Spec PR merged (this folder), then branch `feat/backup-071-ace2-drills` from master in a sibling worktree, `make worktree-init`.
- [ ] Measure on ace2 before writing IaC: `ssh ace2 'id -nG; command -v restic poetry docker; ls ~/.config/sops/age 2>&1'`. Record the output in `verification.md` as the baseline.

## Implementation

### IaC (AC1)

- [ ] [P] [AC1] Test `tests/test_restic_install_shared.py`: `node_backup` and `dev_node` both include `roles/node_backup/tasks/restic.yml` (or the agreed shared path), and no other task file in either role downloads a `restic_` asset. Expected: FAIL (the install lives inline in `node_backup/tasks/main.yml`).
- [ ] [AC1] Move the restic install tasks into the shared file, include it from `node_backup`, and confirm `make provision NODE=bee ENV=prod --check` (or the role's molecule/check path) still shows no change on a node that has restic.
- [ ] [AC1] `dev_node`: include the restic tasks with `backup.r2.restic_version`, install poetry pinned (version in `dev_node` defaults, matching CI's major), and assert the dev user is in the `docker` group (fail provisioning, do not add silently if the group is missing).
- [ ] [AC1] `dev_node`: clone the public kubelab repo into `~/.local/share/kubelab-drill` with `update: false`, owned by the dev user. The drill run moves it, not provisioning.
- [ ] [AC1] `make provision NODE=ace2 ENV=prod` twice: second run `changed=0`. `ssh ace2 test ! -e ~/.config/sops/age/keys.txt`.

### Headscale live split (AC2, AC3)

- [ ] [P] [AC2] Test: `headscale_drill.read_live(run, ssh_target, volume)` returns the node list, user list and key hashes, or None naming what it could not read; `run_drill(live=...)` compares against the given state with no ssh call (fake runner asserts no `ssh` argv). Expected: FAIL.
- [ ] [AC2] Split `run_drill` at the seam; `drill_headscale` calls `read_live` then `run_drill`. Existing `tests/test_headscale_drill.py` stays green unchanged except for the signature.

### Remote run (AC2, AC3)

- [ ] [P] [AC3] Test `tests/test_drill_remote.py`: the builder for a remote run produces an ssh argv with none of the injected values, and the payload on stdin; with a fake runner, the remote entrypoint (`--inputs-stdin`) calls `run_drill` with the payload's values and never imports or builds `ConfigurationManager` (patched to raise). Expected: FAIL.
- [ ] [AC3] Test: after a fake remote run, no file under the work directory contains an injected value; a malformed payload exits non-zero and stderr contains none of its values. Expected: FAIL.
- [ ] [AC2] Test: a dirty tree, and a HEAD that `git branch -r --contains` does not find on `origin`, each refuse with CANNOT CHECK naming the reason, before any ssh. Expected: FAIL.
- [ ] [AC2] [AC3] Implement `toolkit/features/drill_remote.py`: resolve the host from `networking.nodes.<host>` and `networking.ssh_users.homelab`; preflight the tree; over ssh, fetch and detach the checkout at HEAD, `make worktree-init`, then run `toolkit backup drill-<x> --inputs-stdin` with the payload on stdin. An init failure is CANNOT CHECK.
- [ ] [AC2] CLI and Make: `--host` and `--inputs-stdin` on `drill-gitea` and `drill-headscale`; `HOST=` passed through by `backup-drill-gitea` and `backup-drill-headscale`. Without `HOST`, the local path is byte-for-byte today's.

### Runs and knowledge (AC2, AC4, AC5)

- [ ] [AC2] [AC4] From the pushed branch: `make backup-drill-gitea HOST=ace2 ENV=prod` and `make backup-drill-headscale HOST=ace2 ENV=prod`. Record host, commit, snapshot and result in BACKUP-040's and BACKUP-067's `verification.md` (in their archive PRs, or in this PR if they are still open specs on master).
- [ ] [AC5] Runbook section "Running a drill on ace2" in `docs/runbooks/offsite-backup-restore.md`.
- [ ] Lesson if the run teaches something the spec did not predict (start at the next free number).

## Closing

- [ ] Every acceptance criterion is covered by a test or a recorded run, and has a `features.json` entry with an executable, fail-closed verification
- [ ] `make test` green; ruff and mypy clean on touched files
- [ ] `verification.md` filled in
- [ ] Independent adversarial review (`dotf spec review`), then archive and close #2011
