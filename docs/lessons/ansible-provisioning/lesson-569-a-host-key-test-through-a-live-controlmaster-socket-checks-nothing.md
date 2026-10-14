---
id: lesson-569-a-host-key-test-through-a-live-controlmaster-socket-checks-nothing
type: lesson
status: active
created: "2026-10-14"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ssh, security, testing]
---

# A host-key test through a live ControlMaster socket checks nothing

**Context**: ANSIBLE-066 (#2223) made the generated inventory verify every stable node against `~/.ssh/known_hosts_pinned`. To prove it live (AC6), I pinged every node, then pinged rpi3 again with a copy of the pinned file in which rpi3's line carried beelink's key. The second run was supposed to fail.

**Problem**: rpi3 answered `pong` with the wrong key. The inventory was not at fault: Ansible's default `ssh_args` set `ControlMaster=auto` and `ControlPersist=60s`. The first ping had left a master socket for rpi3 open, so the second run went over that socket and opened no new SSH session. A host key is verified only when a connection opens, so nothing compared rpi3 with the altered file. The same reuse would make a run look clean after a node changed its key, for up to 60 seconds after any earlier task on that node.

**Solution**: I re-ran both halves with `-o ControlMaster=no -o ControlPath=none` added to the overridden `ansible_ssh_common_args`. rpi3 then failed with `REMOTE HOST IDENTIFICATION HAS CHANGED`. In the same run, beelink, still carrying its correct key, answered `pong`. The positive run without reuse: 6 of 6 stable nodes answered. Jetson needs `raw` because it runs Python 3.6, and gcp1 is the declared `accept-new` exception.

**Rule**: When a test is about what SSH verifies at connection time (host keys, user keys, `authorized_keys` options), disable multiplexing for that run, or wait out `ControlPersist`. A negative result proves something only if a new session was actually opened. Otherwise a passing run measures the socket, not the configuration.

**Tags**: `#ssh` `#host-keys` `#testing` `#pr-2250`
