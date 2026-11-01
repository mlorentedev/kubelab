---
id: lesson-620-a-deferred-handler-is-lost-when-a-later-role-fails
type: lesson
status: active
created: "2026-10-25"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, handlers, idempotence]
---

# A deferred handler is lost when a later role fails, and the re-run reports changed=0

**Context**: The `gateway` role's lab Wi-Fi AP (NET-005 PR 5) wrote the AP's networkd unit and notified a `networkctl reload` handler. It also notified hostapd's restart and dnsmasq's from its templates. `provision-rpi4.yml` runs several roles after `gateway`.

**Problem**: A notified handler waits for the end of the play, or for the next `flush_handlers`. If a later role fails first, the handler never runs, and nothing records that it was owed. On the re-run the template is already on disk, so its task reports `ok`, nothing is notified, and the play ends at `changed=0` while `wlan0` has no address and hostapd still runs the old config. `changed=0`, the signal we trust to mean "converged", reports the opposite. An independent adversarial review found it by reading the task list, before any live run.

**Solution**: Two changes, both in the role:

- What a later task depends on is a task, not a handler, and it reads the live state. "Read the AP interface's addresses" runs `ip -4 -br addr show dev wlan0` with `check_mode: false`. "Apply the AP interface's address" runs `networkctl reload` and `networkctl reconfigure wlan0` when the unit changed **or** the address is not on the interface. That makes it level-triggered, so a run after a lost handler repairs the state.
- The role flushes its own handlers (`meta: flush_handlers`) after the last task that notifies one, so hostapd and dnsmasq restart inside the role.

Play-level `force_handlers: true` was rejected. It also runs handlers after a failure, which would apply the uplink's netplan after a failed check, and the uplink's ordering exists to prevent exactly that. Tests in `tests/test_gateway_role_tasks.py` assert the flush comes after the last `notify` and that no play sets `force_handlers`. They also evaluate the address condition for "unit changed", "no interface", "another address" and "in place". `make mutate` turned them red for a removed flush and for a condition reduced to "the unit changed".

**Rule**: A handler is edge-triggered and lives only until the play ends. Use one only where losing it costs nothing a re-run cannot see. When a later task, or the next run, depends on the effect, write a task that reads the live state and acts when the state is wrong. When a role's handlers must run whatever happens after it, flush them at the end of the role rather than forcing handlers for the whole play.

**Tags**: `#ansible` `#handlers` `#idempotence` `#pr-2670`
