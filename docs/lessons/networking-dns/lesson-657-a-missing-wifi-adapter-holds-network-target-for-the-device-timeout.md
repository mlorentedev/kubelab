---
id: lesson-657-a-missing-wifi-adapter-holds-network-target-for-the-device-timeout
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, systemd, netplan, edge]
---

# A missing Wi-Fi adapter holds network.target for systemd's 90-second device timeout

**Context**: B14's T3 on the lab edge (NET-005, #2661): unplug the uplink's USB Wi-Fi adapter, cut the power, and read the boot. `make edge-boot-check CASE=no-uplink` passed, but the boot took 2 min 47 s of userspace against 30 s with the adapter in.

**Problem**: netplan generates `netplan-wpa-uplink0.service` with:
- `Requires=` and `After=sys-subsystem-net-devices-uplink0.device`;
- `Before=network.target`;
- a link in `systemd-networkd.service.wants/`.

At boot, systemd-networkd pulls the supplicant in, and the supplicant's start job waits on the device's start job. With no adapter, the device job runs until `JobRunningTimeoutSec=`, which defaults to `DefaultDeviceTimeoutSec=` (90 s). `network.target` waits on the supplicant, so everything after it started 90 s late: docker (and with it the LAN's DNS) and tailscaled. The journal shows it:

```text
[    9.408893] Expecting device sys-subsystem-net-devices-uplink0.device ...
[   99.410969] sys-subsystem-net-devices-uplink0.device: Job ... /start timed out.
[   99.414190] Dependency failed for netplan-wpa-uplink0.service ...
```

`systemd-analyze critical-chain` put `network.target` at 1 min 31.6 s. A drop-in on the supplicant cannot fix it: dependencies set by the generated unit, `Before=network.target` among them, cannot be removed by a drop-in.

**Solution**: bound the device's own start job, the way systemd-fstab-generator bounds a mount's device for `x-systemd.device-timeout=`. The `gateway` role writes `sys-subsystem-net-devices-uplink0.device.d/kubelab-timeout.conf` with `[Unit] JobRunningTimeoutSec=10s`. That is safe because #2766's udev rule starts the supplicant through `SYSTEMD_WANTS` whenever the adapter appears, so an adapter that comes late is still served. `make edge-boot-check` reads the device's `JobRunningTimeoutUSec` and fails on systemd's default, so a bound that did not apply no longer passes unseen, and its `INFO` line gives when `network.target` was reached. #2794.

**Rule**: a generated unit that `Requires=` a device and orders itself before a target makes every boot without that device wait `DefaultDeviceTimeoutSec`. Bound the wait on the device unit (`JobRunningTimeoutSec=` in a `.device.d/` drop-in), not on the unit that needs it. Read a boot check's pass together with the boot's length: a check of the end state cannot see a boot that got there 90 s late.

**Tags**: `#systemd` `#netplan` `#edge` `#issue-2794`
