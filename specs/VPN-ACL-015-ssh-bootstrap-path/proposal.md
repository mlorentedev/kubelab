---
id: "VPN-ACL-015-ssh-bootstrap-path"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-11-02"
issue: "mlorentedev/kubelab#2862"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator approved on 2026-11-02: the control-plane SSH bootstrap path is the only way filtered networks reach Headscale, and the next VPS provision would remove it (13 active, limit 10, 2026-11-02)"
---

# VPN-ACL-015: declare the control-plane SSH bootstrap path on the VPS

## Why

<!-- from issue #2862: VPN-ACL-015: declare the control-plane SSH bootstrap path on the VPS -->

`ts-bridge connect --bootstrap-ssh deployer@<vps>` is how clients on a network that
sinkholes or TLS-inspects `vpn.kubelab.live` reach Headscale (accepted live on
2026-10-20 in ts-bridge CFG-005), and hosts enrolling through ts-bridge's host mode
(mlorentedev/ts-bridge HOST-008) will depend on the same path. It needs an sshd TCP
forward on the VPS. The `ssh_hardening` template renders `AllowTcpForwarding no` for
every user there, while the live VPS lets every account forward anywhere
(`allowtcpforwarding yes`, `permitopen any` for `deployer` and `manu`, read by the
operator on 2026-11-02), so
the next `make provision NODE=vps` silently removes the only control path those
clients have, and until then every account on the VPS, the Ansible one with sudo
included, is an open relay for any key it holds.

## What

- A dedicated account on the VPS, `hs-bootstrap`: no shell, no sudo, in no group
  that grants anything. A `Match User hs-bootstrap` block gives it
  `AllowTcpForwarding local`, `PermitOpen vpn.kubelab.live:443` and nothing else,
  with `PermitTTY no`, `X11Forwarding no`, `AllowAgentForwarding no`,
  `PermitTunnel no` and `ForceCommand /usr/sbin/nologin`. ts-bridge's `ssh -N -D`
  SOCKS forward asks for the control plane by name, which is what `PermitOpen`
  matches.
- Its `authorized_keys` is rendered from SOPS, one public key per enrolled machine
  under a neutral key (`apps.services.core.headscale.bootstrap_ssh_keys.<client-N>` in
  `prod.enc.yaml`, beside the segments, `envs=("prod",)`), each line
  prefixed `restrict,port-forwarding,permitopen="vpn.kubelab.live:443"`. The file is
  owned by root and not writable by the account. Removing a key from SOPS and
  deploying revokes it.
- `deployer` loses its forward in two steps, so there is never a window without a
  proven path: this PR narrows it from `permitopen any` to `vpn.kubelab.live:443`
  (a declared transitional user), and once clients have moved to `hs-bootstrap` a
  second PR empties that list, leaving `deployer` at the template's
  `AllowTcpForwarding no` like every other user.
- Every other node renders exactly the `sshd_config` it renders today.

## Out of scope

- ts-bridge client changes (its docs and examples naming `deployer@`) and host mode
  itself (mlorentedev/ts-bridge HOST-008).
- Minting tagged pre-auth keys for a segment (VPN-ACL-016, #2863), and any Headscale
  ACL change.
- SSH on any node other than the VPS, and the LAN jump host's block.

## Risks / open questions

- [OPEN, until merged] Any `make provision NODE=vps` (tags `ssh`/`security`) run
  before this lands removes `deployer`'s forward and cuts the filtered clients off.
  Do not provision the VPS's SSH tags until the bootstrap account is deployed.
- [OPEN, deploy-time] Control traffic may need a destination other than
  `vpn.kubelab.live:443` (a DERP or STUN endpoint). AC3 proves the path end to end
  from a filtered network; a refused channel shows in the VPS's auth log as
  `refused permitopen`.
- [OPEN, before rollout] The live `sshd_config` is not the template's (the forward is
  a global default, not a `deployer` exception), so the first `ssh` provision of the
  VPS may change more than forwarding. Run it with `--check --diff` first and settle
  every other difference before applying.
- [ACCEPTED] `PermitOpen` matches the requested host string, not the resolved
  address: a client that asks for the IP is refused. ts-bridge's SOCKS dialer sends
  the name; AC3 is the proof.
- [ACCEPTED] Match blocks run to the end of the file. The VPS is not the LAN jump
  host, but the template must stay correct if both blocks are ever rendered; the
  render test covers both.

## Acceptance criteria

- [ ] AC1: A render test proves the VPS's `sshd_config` keeps `AllowTcpForwarding no`
  for every user except `hs-bootstrap`, whose block's only `PermitOpen` is
  `vpn.kubelab.live:443` and which allows no TTY, agent, X11 or tunnel, and that every
  other node still renders its golden file. While `narrow_ssh_user` is set, the
  VPS's SSH user is the one temporary exception, limited to the same single
  destination (removed by AC5).
- [ ] AC2: A test proves `authorized_keys` for `hs-bootstrap` is rendered only from
  SOPS, one `restrict,port-forwarding,permitopen="vpn.kubelab.live:443"` line per key,
  and printed by no task; a key absent from SOPS is absent from the file.
- [ ] AC3: Live, after deploy: a bootstrap key cannot open a shell, a PTY or a forward
  to any other destination, and `ts-bridge connect --bootstrap-ssh hs-bootstrap@<vps>`
  reaches `READY` from a filtered network. A key removed from SOPS stops working after
  the next deploy.
- [ ] AC4: Before changing anything, the live effective config (`sshd -T`) is read and
  the drift this ticket resolves is recorded in `verification.md`.
- [ ] AC5: After the clients have moved, `sshd -T -C user=deployer,...` on the VPS
  reports `allowtcpforwarding no`, and a second deploy reports `changed=0`.

## References

- Issue: mlorentedev/kubelab#2862
- ADR-041 (agent fleet VPN segmentation); VPN-ACL-014 (#2830), VPN-ACL-016 (#2863)
- mlorentedev/ts-bridge#522 (host mode), mlorentedev/ts-bridge#525 (HOST-008 spec)
- `tests/test_ssh_hardening_lan_jump.py` (golden-file pattern for `sshd_config`)
