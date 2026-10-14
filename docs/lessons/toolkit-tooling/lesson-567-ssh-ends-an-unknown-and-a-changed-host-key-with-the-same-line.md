---
id: lesson-567-ssh-ends-an-unknown-and-a-changed-host-key-with-the-same-line
type: lesson
status: active
created: "2026-10-13"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, ssh, host-key, workstation]
---

# ssh ends an unknown and a changed host key with the same line

**Context**: The first `make fetch-kubeconfig ENV=prod` on a new workstation
(the Mac that replaces msi). The workstation had never connected to the VPS.

**Problem**: The fetch failed with "SSH host key for '100.64.0.2' does not
match the one in known_hosts", and suggested `ssh-keygen -R`. No key was
recorded at all. `host_key_hint` matched "Host key verification failed.", but
ssh ends both failures with that line. Under `BatchMode` and the default
`StrictHostKeyChecking ask`, an unknown host prints that line and nothing else.
Measured against the VPS:

```text
unknown:  [No ED25519 host key is known for 100.64.0.2 and you have requested strict checking.]
          Host key verification failed.
changed:  Offending ED25519 key in <file>:<line>
          Host key for 100.64.0.2 has changed and you have requested strict checking.
          Host key verification failed.
```

The first line in brackets appears only with `StrictHostKeyChecking yes`.
Without strict checking, a changed key prints the `REMOTE HOST IDENTIFICATION
HAS CHANGED` banner. The fingerprint msi had recorded for the VPS was identical
to the one presented, so nothing had changed.

**Solution**: Only a changed key names an offending entry, so
`host_key_hint` now treats `offending` or the banner as "changed". A bare
verification failure gets its own message: no key is recorded, verify the
fingerprint out of band and pin it in dotfiles `ssh/known_hosts`. It suggests
no `ssh-keygen -R`, because there is nothing to remove, and no keyscan, because
that would be trust on first use.

**Rule**: When you classify a CLI failure from stderr, match the line that
only one cause prints, not the summary line every cause ends with. A diagnosis
that names the wrong cause is worse than none. It sends the operator to delete a
key that never existed, or to doubt a host that is fine.

**Tags**: `#ssh` `#host-key` `#1380` `#1261`
