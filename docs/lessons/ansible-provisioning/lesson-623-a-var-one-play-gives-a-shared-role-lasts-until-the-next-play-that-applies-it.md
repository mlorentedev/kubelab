---
id: lesson-623-a-var-one-play-gives-a-shared-role-lasts-until-the-next-play-that-applies-it
type: lesson
status: active
created: "2026-10-25"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, node-notify, rpi4, idempotence]
---

# A var one play gives a shared role lasts only until the next play that applies the role to the same host

**Context**: #2684 needed the edge's own units to page while the rest of rpi4 stayed at `log`. The first design of #2688 added a map, `node_notify_unit_severity`, which the rpi4 play passed to `node_notify` and the role rendered into `kubelab-notify.sh`.

**Problem**: `provision-rpi4.yml` is not the only play that applies `node_notify` to rpi4. `maintain.yml` (`hosts: all`), `backup.yml` and every `provision-*.yml` apply it too, and they pass no map. Each of them re-renders the script with the default `{}`. The first maintenance run after a provision would have dropped the edge's units back to `log`, and nothing would have failed: each play is idempotent on its own, and the node simply holds whatever the last play to run gave it. The independent review caught it as a Blocker before merge. Every test passed, because each rendered the role from one caller.

This is lesson-519's mechanism with a different input. There the input was the privilege a caller lends the role (`~` under `become`); here it is the vars a caller passes. Either way, a role applied to one host by several plays gives one result per caller, and the host flips between them.

**Solution** (#2688): the value moved to the thing it describes. A unit that needs a person declares it beside the line that wires it to the notifier, `Environment=KUBELAB_NOTIFY_SEVERITY=page`, and the script reads it at run time with `systemctl show -p Environment <unit>`. The role renders the same script for every caller, so no play can undo another.

**Rule**: Before a play passes a var to a role, list every play that applies that role to the same host (`grep -rn "roles/<role>" infra/ansible/playbooks`, then each one's `hosts:`). If any of them omits the var, the value is not durable. Move it to state that only one place writes: a file the owning role installs, the unit itself, or the SSOT that every caller reads. Plays for different hosts may differ freely. The hazard is two plays for one host, and `maintain.yml` and `backup.yml` make that true of every node.

**Tags**: `#ansible` `#idempotence` `#node-notify` `#issue-2684` `#pr-2688`
