---
tags: [spec, verification, templates]
created: "2026-11-02"
---

# Verification - VPN-ACL-015-ssh-bootstrap-path

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> `tests/test_ssh_hardening_bootstrap_forward.py`:
  `test_the_vps_renders_the_golden_file_plus_one_bootstrap_block`,
  `test_both_blocks_render_each_closed_and_the_global_default_stays_no`,
  `test_a_malformed_forward_is_refused` (13 cases),
  `test_sshd_itself_limits_each_user_to_what_was_declared` (CI only: no sshd on the
  Windows workstation); `tests/test_ssh_hardening_lan_jump.py` still holds every other
  host to its golden file; `test_sshd_and_the_keys_open_the_same_single_destination`.
- [x] AC2 -> `tests/test_headscale_bootstrap_ssh.py`:
  `test_each_key_gets_one_line_restricted_to_the_control_plane`,
  `test_a_key_absent_from_sops_is_absent_from_the_file`,
  `test_a_malformed_key_is_refused` (10 cases),
  `test_the_file_is_root_owned_and_its_render_is_never_printed`,
  `test_keys_reach_the_role_only_from_sops`; catalog in
  `tests/test_secrets_headscale_catalog.py`.
- [x] AC3 -> live, 2026-11-02 (below). The revocation half (a removed key refused after a
  deploy) is held by `test_a_key_absent_from_sops_is_absent_from_the_file`; not exercised live.
- [x] AC4 -> drift read on 2026-11-02, before any change (below).
- [ ] AC5 -> live check `<date>`

## Drift before the change (AC4)

Read by the operator on the VPS on 2026-11-02:

```text
$ sudo sshd -T -C user=deployer,host=x,addr=1.2.3.4 | grep -iE 'allowtcpforwarding|permitopen'
allowtcpforwarding yes
permitopen any
$ sudo sshd -T -C user=manu,host=x,addr=1.2.3.4 | grep -iE 'allowtcpforwarding|permitopen'
allowtcpforwarding yes
permitopen any
```

Both users get the same answer, so the forward is the VPS's global setting (OpenSSH's
default), not a per-user exception: the live `sshd_config` is not the one this
template renders, which matches `deploy-harden-nodes.yml` noting the VPS was
"already hardened by Hetzner". The template (`infra/ansible/roles/ssh_hardening/templates/sshd_config.j2`) renders
`AllowTcpForwarding no` for every user on the VPS and no `PermitOpen`. So the live
host allows every account, `deployer` (Ansible, with sudo) included, to forward to
any destination, and the next provision of the VPS's `ssh` tags would remove the
bootstrap path the filtered clients use.

## Test status

- `pytest tests/test_headscale_bootstrap_ssh.py tests/test_ssh_hardening_bootstrap_forward.py
  tests/test_ssh_hardening_lan_jump.py tests/test_headscale_segments.py tests/test_headscale_role.py`:
  134 passed, 2 skipped (the `sshd -T` cases; Windows, 2026-11-02). All `tests/test_secret*.py`:
  216 passed.
- Mutations (`toolkit tools mutate`), all RED: `restrict` removed from the key line;
  `PermitOpen *` in provision.yml; `PermitTTY yes`; the same-user check removed.
- Live checks: see "Rollout evidence".

## Rollout evidence

All on 2026-11-02. The deploy and the provision ran on the operator's controller (this
workstation has no Ansible); the checks below ran from the corporate workstation, a
filtered network where `vpn.kubelab.live` resolves to the Palo Alto sinkhole.

- `make deploy TARGET=vps ENV=prod`: `changed=3`, `failed=0` (account, `.ssh`, keys).
- Base `provision.yml` limited to the VPS, `-t ssh`: `ok=11 changed=3`. A fresh
  `ssh vps-pub` session opened afterwards, with the previous one kept as fallback.
- `ssh hs-bootstrap id` -> `This account is currently not available.` (exit 1).
- `ssh -W 127.0.0.1:22 hs-bootstrap` -> `administratively prohibited` (exit 255).
- `ssh -W vpn.kubelab.live:443 hs-bootstrap` -> channel opened, the ingress answered.
- The operator's `projects-toolkit-gitea` ts-bridge profile moved from `deployer@` to
  `hs-bootstrap`: `READY local=127.0.0.1:1081`, its `ssh` child is
  `ssh -N -D 127.0.0.1:1056 ... hs-bootstrap`, and `gitea.kubelab.live/api/healthz`
  through it answered HTTP 200 three times.
- A fresh tsnet node through `hs-bootstrap` reached Headscale, which answered
  `authkey expired` (the workstation's `TS_AUTHKEY` had lapsed): the control path
  works independently of node state.
- Each bridge start logs one `channel 2: open failed: administratively prohibited`.
  The bridge reaches READY and serves traffic regardless. The embedded DERP region
  (999) failed the same way before the change (`CONNECT dial to vpn.kubelab.live:443:
  unexpected EOF`, 29 times on 2026-11-02 while still on `deployer@`), and the data
  plane runs over Tailscale's public DERP; the refused destination is not logged.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The VPS's host var is a `provision.yml` `set_fact`, not a generator host var: its
  destination derives from `apps.services.core.headscale.domain`, which the
  inventory generator does not read.
- The transitional block is `narrow_ssh_user: true`, so the SSH user is not repeated
  in common.yaml (it is `networking.ssh_users.cloud`).
- The key list is checked at deploy by the role, not by `value_pattern`, which
  checks one whole value and this entry is a mapping.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/VPN-ACL-015-ssh-bootstrap-path/` -> `specs/archive/VPN-ACL-015-ssh-bootstrap-path/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
