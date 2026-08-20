---
id: lesson-356-unmatched-host-pattern-is-a-warning
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, backup, ci-automation]
---

# An Ansible play whose `hosts:` pattern matches nothing succeeds

**Context**: BACKUP-044 Part 3 (#1179) shipped a playbook with two plays, split
by availability class, covering the four nodes that declare `backup.sources`:
Beelink (Gitea), RPi3 (Uptime Kuma), RPi4 (Pi-hole), VPS (Headscale). It was
reviewed, carried 25 render tests, and merged green.

**Problem**: It backed up one node of four, and would have reported success.

The `hosts:` patterns were written as `kubelab-beelink`, `kubelab-rpi3`,
`kubelab-rpi4`, `kubelab-vps`. Only the VPS carries that prefix in the
generated inventory; the generator names the rest from
`networking.nodes.<key>.hostname`, which is `beelink`, `rpi3`, `rpi4`.

```
$ ansible-playbook --list-hosts -i generated/prod/hosts.yml playbooks/backup.yml
[WARNING]: Could not match supplied host pattern, ignoring: kubelab-rpi3
[WARNING]: Could not match supplied host pattern, ignoring: kubelab-beelink
[WARNING]: Could not match supplied host pattern, ignoring: kubelab-rpi4
  play #1 (kubelab-vps,kubelab-rpi3):  hosts (1):  kubelab-vps
  play #2 (kubelab-beelink,kubelab-rpi4):  hosts (0):
```

**A play with zero hosts is not an error.** Ansible emits a WARNING and exits
0. So the failure is invisible from every angle that was checked: the playbook
is valid YAML, `--syntax-check` passes, the run goes green, and the only signal
is a warning line in output nobody reads on a successful run.

Two guards were in place and neither could see it:

- The syntax gate added the same day (#1180) does not resolve host patterns —
  confirmed by measurement, and its own docstring says so.
- A test *did* claim to check node coverage. It stripped `kubelab-` from the
  play patterns and compared the result to `backup.sources`. `kubelab-beelink`
  stripped to `beelink`, which is declared, so it passed — while `beelink` was
  the name the inventory actually used and the pattern matched nothing. The
  test compared the file to its own derivation, so it could only ever pass.

The playbook also carried a comment asserting that inventory hostnames "carry a
`kubelab-` prefix". The patterns were written from that claim. **A false
assumption written down as documentation is what carried it through review** —
a reader checking the patterns against the comment finds them consistent.

**Solution**: Patterns corrected to `kubelab-vps,rpi3` and `beelink,rpi4`;
`--list-hosts` then resolves 2 and 2. The coverage test now asserts every play
pattern is a member of the inventory's namespace, derived the way
`generator_ansible.py` derives it, with a second test asserting the generator
still derives it that way. Verified to fail: restoring the old patterns turns
both red.

Fleet measurement while fixing it: against the *generated* inventory,
`backup.yml` was the only one of 20 playbooks with an unresolved pattern. An
earlier measurement suggesting 11 of 20 was taken against the committed static
inventory, which is incomplete — the wrong baseline made a buildable gate look
like one that would inherit a backlog.

**Rule**: For a playbook, `--syntax-check` is not evidence it will do anything.
The check that a play will act is `--list-hosts` against the inventory it will
really run with, and the number to read is `hosts (N)`, not the exit code.

And when a test's subject is a name that must match something outside the file,
assert against the artifact that does the matching — never against a
transformation of the value under test. A test that derives the expected value
from the actual value passes by construction, and reports coverage it does not
have.

**Tags**: `#ansible` `#backup` `#silent-failure` `#pr-1179` `#pr-1186`
