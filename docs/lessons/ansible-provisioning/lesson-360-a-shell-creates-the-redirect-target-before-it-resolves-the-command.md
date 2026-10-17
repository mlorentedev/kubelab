---
id: lesson-360-a-shell-creates-the-redirect-target-before-it-resolves-the-command
type: lesson
status: active
created: "2026-08-21"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, shell, backup, node-backup]
---

# A shell creates the redirect target before it resolves the command, so a missing command yields a corrupt artifact rather than no artifact

**Context**: The first real deploy of the `node_backup` role (BACKUP-044). Its
install step unpacked restic's release asset with the obvious one-liner:

```yaml
shell: >
  bunzip2 -c /tmp/restic_{{ version }}_linux_{{ arch }}.bz2
  > {{ node_backup_restic_install_path }}
```

**Problem**: The RPi4 has no `bunzip2`, so the task failed `rc=127` —
`/bin/sh: 1: bunzip2: not found`. The expected outcome of a missing command is
that nothing happens. What actually happened is that `/usr/local/bin/restic`
was created, 0 bytes, before the shell ever looked for `bunzip2`.

Redirections are set up as part of building the command's execution
environment, which happens *before* the command is resolved and executed.
`> file` truncates or creates the target regardless of whether the command on
the left exists, or exits non-zero, or dies half-way through writing.

So the failure mode is not "restic was not installed". It is "a file named
`restic` now sits on the `PATH` where the capture and ship scripts expect a
working binary". The task that follows, `Make restic executable`, has no
`when:` — on any run that gets past the decompress it would happily `chmod +x`
whatever is there.

**Solution**: Decompress to a temp path on the same filesystem and move it into
place, so the destination only ever appears complete:

```yaml
shell: >
  rm -f {{ node_backup_restic_install_path }}.tmp
  && python3 -c 'import bz2,shutil,sys; shutil.copyfileobj(bz2.open(sys.argv[1],"rb"), open(sys.argv[2],"wb"))'
  /tmp/restic_{{ version }}_linux_{{ arch }}.bz2
  {{ node_backup_restic_install_path }}.tmp
  && mv {{ node_backup_restic_install_path }}.tmp {{ node_backup_restic_install_path }}
```

`&& mv` never runs on failure, so a partial write is never promoted. `rm -f`
runs *first* rather than as cleanup after a failure, so the next attempt starts
from nothing without needing an `always` block to be reliable. Same filesystem
matters: `mv` within a filesystem is a rename, which is atomic; across one it
is a copy, which reintroduces the partial-file window this fix exists to close.

Guarded in `tests/test_node_backup_role.py`: the install path may appear only
as the move's destination, never as a write target. Proven red against the old
form before being trusted green.

**Rule**: Never redirect straight onto a path that something else will later
read, execute, or serve. Write to `<target>.tmp` beside it and `mv` into place.
The rule holds for any generated artifact — a binary, a rendered config, a
database dump — and it holds for *every* failure of the producing command, not
just a missing one: a command that exits mid-write leaves exactly the same
truncated file. Read `cmd > file` as "create `file`, then try `cmd`", because
that is the order the shell does it in.

Corollary for review: `rc=127` in a task log reads like "nothing happened".
Check what the redirect left behind before believing it.

**Tags**: `#ansible` `#shell` `#backup` `#pr-1199` `#issue-1198`
