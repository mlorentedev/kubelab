---
id: lesson-622-a-kernel-parameter-one-node-must-lose-can-be-another-nodes-wi-fi-country
type: lesson
status: active
created: "2026-10-25"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, rpi_boot, raspberry-pi, wifi]
---

# A kernel parameter one node must lose can be another node's Wi-Fi country

**Context**: The RPi4's `cmdline.txt` carries `cfg80211.ieee80211_regdom`, added by hand. kmod applies command-line module options after `/etc/modprobe.d`, and the kernel keeps the last value, so the per-site regulatory domain the edge writes to modprobe.d could never load (#2668). `rpi_boot` owns the command line, and the obvious fix was to make it remove that token.

**Problem**: `rpi_boot` also runs on rpi3, which has no network but Wi-Fi and no screen. On Raspberry Pi OS the same token is the Wi-Fi country. `raspi-config`'s `do_wifi_country` (bookworm branch) writes it into `cmdline.txt` with `sed`, removing any earlier value first. A removal declared as the role's default would have stripped rpi3's country on its next provision, the next boot would have used the world domain, and a node that cannot be reached by hand would have depended on its access point's channel staying inside it. Nothing in the role's name or its first user pointed at rpi3.

**Solution**: `rpi_boot_absent_params` defaults to `[]`, and only `provision-rpi4.yml` declares `cfg80211.ieee80211_regdom`. `tests/test_rpi_boot_role.py` fails if the default lists anything or if any other play passes the variable. A node with the memory controller and nothing declared never reads its command line.

**Rule**: Before giving a shared role a destructive default, list every play that runs it and ask what that value means on each one's OS. Removing a parameter is a per-node decision, so the play that owns what the parameter overrides declares it, and the role's default does nothing.

**Tags**: `#rpi_boot` `#issue-2668`
