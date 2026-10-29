---
id: lesson-646-a-unit-started-with-networkd-never-starts-for-an-adapter-that-appears-later
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, netplan, systemd, udev, rpi4, hotplug]
---

# A unit started with networkd never starts for an adapter that appears later

**Context**: The edge's uplink is a USB Wi-Fi adapter, named `uplink0` by a `.link` file. netplan writes its supplicant, `netplan-wpa-uplink0.service`, and the gateway role wrote a CAKE shaper enabled into the adapter's device unit (`WantedBy=sys-subsystem-net-devices-uplink0.device`). The hard-reset test of NET-005 (B14, #2661) unplugs and replugs the adapter with the edge running.

**Problem**: Two failures with one cause: both units were wired to the adapter in ways that only work at boot, or only when it is present.

- **After a replug the uplink never came back.** `uplink0` reappeared, but 2.5 minutes later `networkctl` read `no-carrier configuring`, no `wpa_supplicant` ran and the supplicant unit was inactive. netplan 1.1.2 installs the supplicant only into `systemd-networkd.service.wants/`, so it starts with networkd at boot. When the device appears later, nothing starts it. Its `Requires=` on the device does not help: that stops it when the device is explicitly stopped, never on an unplug. It does not start it on a replug either.
- **With the adapter missing, the shaper failed every 90 s.** systemd follows a link in a device's `.wants/` whenever a start job for the device is enqueued, whether or not the device exists. Each job timed out after `JobRunningTimeoutUSec` (90 s), the shaper failed with result `dependency`, and its `OnFailure=` notifier ran and failed too, because there was no route out. That second report was for an outage the liveness check already owns. Which unit enqueues the device's job every 90 s was observed and not traced. The fix does not depend on it, because the shaper is no longer pulled at all.

**Solution**: Want the units from udev, and bind the supplicant to the device (#2766):

- `/etc/udev/rules.d/90-kubelab-uplink.rules`: `ACTION=="add", SUBSYSTEM=="net", NAME=="uplink0", ENV{SYSTEMD_WANTS}+="netplan-wpa-uplink0.service kubelab-edge-shaper.service"`. systemd acts on `SYSTEMD_WANTS=` only when the device first becomes active (systemd.device(5)). So a replug starts both units, and a missing adapter pulls in nothing. **Correction (2026-10-29):** matched on `add` alone, the rule started nothing on a real replug, because a renamed adapter becomes active on the move event that follows its add. The rule now matches `ACTION!="remove"`; see lesson-650. The file sorts after `80-net-setup-link.rules`, which applies the `.link` file's name: `NAME==` matches nothing before it. The role writes it with `validate: udevadm verify --resolve-names=never %s`.
- A drop-in on the supplicant, `BindsTo=sys-subsystem-net-devices-uplink0.device`. The supplicant now stops when the adapter leaves, so the next appearance starts it.
- The shaper has no `[Install]`. The role removes its old link with `file: state=absent`, because Ansible does not undo the `enabled: true` it stopped declaring.

`tests/test_edge_uplink_replug.py` renders the rule and checks it with `udevadm verify`, and fails on any role unit installed into a net device's `.wants/`. The live proof is #2766's done-when: a replug brings the lease, the route and the tailnet back within 2 minutes.

**Rule**: For a unit that must run whenever a hot-pluggable device is present, want it from udev with `SYSTEMD_WANTS`, never with `WantedBy=` the device, and bind it to the device with `BindsTo=`. A unit pulled in by a service at boot is a boot-time unit, whatever its `Requires=` says.

**Tags**: `#net-018` `#net-005` `#systemd` `#udev` `#pr-2768`
