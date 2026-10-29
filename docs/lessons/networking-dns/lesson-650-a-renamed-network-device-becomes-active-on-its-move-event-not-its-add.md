---
id: lesson-650-a-renamed-network-device-becomes-active-on-its-move-event-not-its-add
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, systemd, udev, rpi4, hotplug]
---

# A renamed network device becomes active on its move event, not its add

**Context**: #2766 (lesson-646) made the edge's uplink come back after a replug with a udev rule, `ACTION=="add", SUBSYSTEM=="net", NAME=="uplink0", ENV{SYSTEMD_WANTS}+="netplan-wpa-uplink0.service kubelab-edge-shaper.service"`. It was checked by rendering the rule, by `udevadm verify`, and by `udevadm test --action=add /sys/class/net/uplink0`, which printed the property.

**Problem**: On the first real replug, during NET-005's hard-reset test (B14, #2661), neither unit started. Their `ConditionTimestamp` stayed empty, and PID 1 logged no job for them. `udevadm monitor --udev --property` on a second replug showed why:

- The kernel names the adapter `wlan1`. Its **add** event is where udev applies `10-kubelab-uplink.link` and renames it, so that event carries `SYSTEMD_WANTS` and `ID_RENAMING=1`. systemd does not treat a device being renamed as ready.
- The rename makes the kernel send a **move** event. udev runs the rules again for it, and the device unit becomes active on it. The rule matched `add` only, so the move event carried no `SYSTEMD_WANTS`, and the device unit came up with `Wants=` empty.

`udevadm test --action=add` on the already-renamed device was a false pass: it ran the rules once, on an interface already called `uplink0`, so no rename and no move followed. On systemd 255 it also writes its result into the udev database, so `udevadm info` afterwards shows a property the real event never left there.

**Solution**: Match every event but remove, `ACTION!="remove"`, as systemd's own `99-systemd.rules` does for the properties PID 1 reads. `tests/test_edge_uplink_replug.py` fails on any other `ACTION` condition. A change event that lists the same units starts nothing new: systemd starts only units added to the list.

**Rule**: A udev property that PID 1 reads (`SYSTEMD_WANTS`, `SYSTEMD_ALIAS`, `TAG+="systemd"`) goes on every event but remove. Each event replaces the device's database entry, and the event that makes a device active is not always the first. Prove a hotplug rule with a physical replug and `udevadm monitor`, never with `udevadm test` on a device that is already present.

**Tags**: `#net-018` `#net-005` `#systemd` `#udev` `#lesson-646`
