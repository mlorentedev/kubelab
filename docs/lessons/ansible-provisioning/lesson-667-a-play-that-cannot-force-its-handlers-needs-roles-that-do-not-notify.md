---
id: lesson-667-a-play-that-cannot-force-its-handlers-needs-roles-that-do-not-notify
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible, handlers, lab-edge]
---

# A play that cannot force its handlers needs its later roles to notify nothing

**Context**: A play's roles share one handler phase. A task that fails the play drops every handler still pending, and the rerun finds the files already written, so it fires none of them. Behind the lab edge a play fails on purpose when a sized pull or upgrade outlasts its budget (#2742, #2809). base_system, ssh_hardening and node_notify notify handlers and do not flush them, so a later role's failure dropped theirs (#2824).

**Problem**: `force_handlers: true` keeps them: the handlers run at the end of the play, where they would have run had it passed. Ten plays behind the edge take it. The edge's own play cannot, because the gateway role's netplan handlers must run in the order the uplink needs, and the gateway role flushes them itself at three points. A failure after the play's last flush still dropped what the later roles notified. On the edge those were coredns and glances. Neither handler changed anything when it ran: `verify coredns` and `verify pihole` repeated the in-task waits without their retries, and `Restart glances` ran a second `up -d` after the in-task one and reported it as a change.

**Solution**: The two handlers are removed, so no role after the edge's last flush notifies at all. `tests/test_play_handlers.py` requires `force_handlers: true` on every play behind the edge that notifies, except the gateway's, and fails if a role after the edge's last flush notifies. Its message gives the three fixes. Five mutations went red under `make mutate`: a notify added to node_maintenance, docker's flush removed, `force_handlers` turned off on bee, the edge's play forced, and the glances notify restored.

**Rule**: Where a play cannot take `force_handlers`, act on a `register`ed change in the task instead of notifying. A flush inside a role flushes the whole play, so it belongs only in a role that only that play runs.

**Tags**: `#ansible` `#handlers` `#adr-075` `#issue-2824`
