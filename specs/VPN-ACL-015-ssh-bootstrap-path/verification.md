---
tags: [spec, verification, templates]
created: "2026-11-02"
---

# Verification - VPN-ACL-015-ssh-bootstrap-path

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 -> test `<name>`
- [ ] AC2 -> test `<name>`
- [ ] AC3 -> live check `<date>`
- [ ] AC4 -> drift read on 2026-11-02, before any change (below). Still to read: the
  same command for a non-`deployer` user, to confirm the forward is per-user.
- [ ] AC5 -> live check `<date>`

## Drift before the change (AC4)

Read by the operator on the VPS on 2026-11-02:

```text
$ sudo sshd -T -C user=deployer,host=x,addr=1.2.3.4 | grep -iE 'allowtcpforwarding|permitopen'
allowtcpforwarding yes
permitopen any
```

The template (`infra/ansible/roles/ssh_hardening/templates/sshd_config.j2`) renders
`AllowTcpForwarding no` for every user on the VPS and no `PermitOpen`. So the live
host allows `deployer`, the Ansible account with sudo, to forward to any
destination, and the next provision of the VPS's `ssh` tags would remove the
bootstrap path the filtered clients use.

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

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
