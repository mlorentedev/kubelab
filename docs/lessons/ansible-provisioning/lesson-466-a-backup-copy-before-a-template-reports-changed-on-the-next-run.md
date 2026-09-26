---
id: lesson-466-a-backup-copy-before-a-template-reports-changed-on-the-next-run
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, idempotence, headscale, ops-023]
---

# A "back up the current file" task before a template reports `changed` on the run after every change

**Context**: OPS-023 PR 2 changed the Headscale ACL and deployed it with `make deploy TARGET=vps ENV=prod`. The acceptance criterion was the usual one: run it twice, and the second run must report `changed=0`.

**Problem**: the second run reported `changed=1`. The change came from `Back up current ACL policy (for auto-revert)`, a `copy: remote_src` of the live policy to `policy.hujson.prev`. After run 1, `.prev` still held the old policy and the live file held the new one, so run 2 copied the new one over and reported it. Only run 3 was clean. The pattern hides under any "back up, then template" pair: a snapshot task always trails the thing it snapshots by one run.

**Solution**: `changed_when: false` on the backup copy (#1838). It is bookkeeping for the auto-revert, not a change to what the service enforces, and the template task right after it is what reports a real policy change. After the fix, run 3 reported `changed=0` against a live deploy.

**Rule**: when the second run is not `changed=0`, read which task changed before assuming drift. A task that copies state for rollback reports what it copied, not what it changed, so mark it `changed_when: false` and let the task that writes the managed file carry the signal. And prove idempotence on the run AFTER a real change, because a run with nothing to do cannot expose this.

**Tags**: `#idempotence` `#headscale` `#ops-023` `#pr-1838`
