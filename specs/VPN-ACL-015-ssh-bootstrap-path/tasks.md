---
tags: [spec, tasks, templates]
created: "2026-11-02"
---

# Tasks - VPN-ACL-015-ssh-bootstrap-path

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feature/vpn-acl-015-ssh-bootstrap` ✓ 2026-11-02
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-11-02
- [x] [AC4] Live drift read and recorded in `verification.md` before any change ✓ 2026-11-02
- [x] [AC4] Read `sshd -T -C user=manu,...` on the VPS too: same answer, so the forward
  is a global default ✓ 2026-11-02

## Implementation

Ownership: `ssh_hardening` alone writes `sshd_config`; the `headscale` role (run by
`deploy-vps`, which already decrypts SOPS) owns the account and its keys. The
declaration is `networking.vps.ssh_bootstrap: {user: hs-bootstrap, permit_open:
"vpn.kubelab.live:443"}` in `common.yaml`, handed to the VPS alone as host vars by
`generator_ansible.py`, the same path as `lan_jump`.

- [x] [P] [AC1] In `tests/test_ssh_hardening_bootstrap_forward.py`, write
  `test_the_vps_renders_the_golden_file_plus_one_bootstrap_block`: render
  `sshd_config.j2` with `ssh_bootstrap_forward={user, permit_open}`, expect the
  golden file plus a trailing `Match User hs-bootstrap` block with
  `AllowTcpForwarding local`, `PermitOpen vpn.kubelab.live:443`, `PermitTTY no`,
  `X11Forwarding no`, `AllowAgentForwarding no`, `PermitTunnel no`,
  `ForceCommand /usr/sbin/nologin` (plus `AllowStreamLocalForwarding no`, which the
  global section leaves at OpenSSH's `yes`). Run
  `poetry run pytest -o addopts= tests/test_ssh_hardening_bootstrap_forward.py -q`.
  Expected: FAIL (block absent).
- [x] [AC1] Add the block to `infra/ansible/roles/ssh_hardening/templates/sshd_config.j2`
  behind `ssh_bootstrap_forward` (default `{}` in `defaults/main.yml`). Rerun.
  Expected: PASS, and `tests/test_ssh_hardening_lan_jump.py` still PASS. ✓ 2026-11-02,
  15 passed; the two `sshd -T` tests skip on Windows and run in CI.
- [x] [AC1] Test `test_both_blocks_render_each_closed_and_the_global_default_stays_no`:
  with jump targets and the bootstrap forward together, the global
  `AllowTcpForwarding no` is unchanged and each Match block carries its own complete
  set. Then a test that `sshd -t` accepts the render (skip where no `sshd`). Expected:
  FAIL, then PASS after ordering the blocks.
- [ ] [P] [AC1] Test in `tests/test_ssh_hardening_bootstrap_forward.py` that the
  generated inventory hands `ssh_bootstrap_forward` to the VPS host and to no other
  host, read from `common.yaml`. Expected: FAIL. Implement in
  `toolkit/features/generator_ansible.py` and declare `networking.vps.ssh_bootstrap`
  in `common.yaml`; regenerate the inventory. Expected: PASS; the golden-file test
  for every other host still PASS.
- [ ] [P] [AC2] In `tests/test_headscale_bootstrap_ssh.py`, test that the `headscale`
  role creates `hs-bootstrap` with shell `/usr/sbin/nologin`, no groups, and renders
  `authorized_keys` (`/home/hs-bootstrap/.ssh/authorized_keys`, file and directory
  owned by root so the account cannot rewrite them, which `StrictModes` accepts) with one
  `restrict,port-forwarding,permitopen="vpn.kubelab.live:443" <key>` line per SOPS
  entry, with `no_log: true` on the render. Evaluate the role's own Jinja as
  `test_headscale_segments.py` does. Expected: FAIL.
- [ ] [AC2] Implement the tasks in `infra/ansible/roles/headscale/tasks/` and pass
  `secrets.apps.services.core.headscale.bootstrap_ssh_keys` from `deploy-vps.yml`.
  The account and file exist only when `ssh_bootstrap_forward` is declared; an empty
  mapping renders an empty file (every key revoked), never a missing one. Expected: PASS.
- [ ] [AC2] Register `apps.services.core.headscale.bootstrap_ssh_keys` in
  `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`, `envs=("prod",)`, kind
  EXTERNAL, neutral keys), with a test that refuses a key line carrying options or
  more than one key. Expected: FAIL, then PASS.
- [x] [AC5] Test that `ssh_bootstrap_forward.transitional_users` (`[deployer]` in
  `common.yaml` for now) renders a Match block per user with the same single
  `PermitOpen`, and that an empty list renders none. Expected: FAIL, then PASS. This
  narrows `deployer` from `permitopen any` to the control plane while clients move;
  the list is emptied by a second PR once AC3 holds.
- [ ] [AC1] [AC2] `make mutate` on the Match block's `PermitOpen` and on the
  `restrict` prefix. Expected: both RED.
- [ ] Update `docs/runbooks/headscale-setup.md` (enrol and revoke a bootstrap key; also
  correct its claim that the segments live in `common.enc.yaml`: they are in
  `prod.enc.yaml`) and
  the CLAUDE.md RPi4-jump-host gotcha's sibling line for the VPS.

## Rollout (operator, in this order)

- [x] [AC3] Operator workstation's key (ed25519, no passphrase: it can only reach the
  public control plane, and ssh-agent is disabled there) written to `prod.enc.yaml` as
  `bootstrap_ssh_keys.client-1` ✓ 2026-11-02. Lab hosts add theirs at enrolment.
- [ ] [AC3] Write each enrolled machine's public key to SOPS, then
  `make deploy TARGET=vps ENV=prod`: creates `hs-bootstrap` and its keys. No sshd
  change yet.
- [ ] [AC3] `make provision NODE=vps ENV=prod TAGS=ssh` in check mode with `--diff`
  first: the live file is not the template's, so record every difference and settle
  each before applying.
- [ ] [AC3] `make provision NODE=vps ENV=prod TAGS=ssh`: renders the `hs-bootstrap`
  block and narrows `deployer` to `vpn.kubelab.live:443`, so existing clients keep
  working. Read `sshd -T` for both users.
- [ ] [AC3] Live: `ssh hs-bootstrap@<vps>` gets no shell and no PTY;
  `ssh -N -L 9999:127.0.0.1:22 hs-bootstrap@<vps>` is refused;
  `ts-bridge connect --bootstrap-ssh hs-bootstrap@<vps>` reaches `READY` from the
  corporate network.
- [ ] [AC3] Remove one test key from SOPS, deploy, and prove it is refused.
- [ ] [AC5] Move every client to `hs-bootstrap`; second PR empties
  `transitional_users`; provision; `sshd -T -C user=deployer,...` reports
  `allowtcpforwarding no`; a second provision and deploy report `changed=0`.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/VPN-ACL-015-ssh-bootstrap-path/features.json`):

```json
[
  {
    "id": "VPN-ACL-015-ssh-bootstrap-path-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
