---
id: lesson-309-five-candidate-triggers-eliminated-and-the-re
type: lesson
status: active
created: "2026-08-11"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Five candidate triggers eliminated, and the reboot turned out to be the repair

**Context:** The 2026-08-10 entry above left the cause of the DNAT flush unsettled and named the confound. The attack plan on #959 opened with a ten-minute causal test that had never been run.

**Problem:** Every candidate failed to reproduce it. On beelink and again on ace1 — deliberately chosen for opposite Docker generations, 29.7.2 and 29.3.1 — `ufw reload`, `ufw disable && ufw --force enable`, `systemctl restart ufw` and `systemctl restart docker` each left the DNAT count unchanged and every probe at 200. That is five candidates across two Docker versions with zero reproductions.

The fifth candidate is the one worth naming: the plan tested the two ufw **CLI** paths, but `base_system` uses neither — `tasks/main.yml:96` is `notify: restart ufw`, whose handler is `service: state=restarted`. That goes through `ufw.service` → `/lib/ufw/ufw-init`, which flushes tables on stop and restores only ufw's own rules on start. Mechanically a far better suspect than `ufw reload`, and it was in our own repo the whole time.

**Solution:** Candidate 3 (a host reboot) was answered without running it, in the opposite direction to the guess. `docker inspect` separates what was recreated from what was merely started: on rpi4, `glances` was `created` at 01:14Z by the remedy, while `pihole` and `coredns` were created in March and only **started** at 01:03Z by the boot. All six of rpi4's DNAT rules are present and both services answer. Nothing recreated pihole or coredns — **a reboot repairs this, it does not cause it.**

The VPS sharpens it further: it has not rebooted since 2026-06-21, its headscale container was never recreated, and headscale's rules are back. The likely mechanism is that creating *any* container makes dockerd rebuild the whole chain, which would make the earlier "recreating a container restores its rules" correct but understated.

**Rule:**
- **A correlation with a perfect sample can still be wrong about mechanism.** The between-node correlation here had no exceptions and died in eight seconds to one intervention. When a confound cannot be separated by observation, trigger the event and watch — do not collect more observations.
- **`ufw reload`, `ufw disable/enable` and `systemctl restart ufw` are three different operations.** The CLI paths rebuild only ufw's chains; the unit path goes through `ufw-init`, which is a hammer. Testing "ufw" means naming which one.
- **Check the whole line before concluding from a log.** `dpkg.log` upgrade lines are `date time upgrade pkg OLD NEW`; an `awk '{print $1..$5}'` prints the version being *replaced*, so every upgrade reads as its predecessor. That truncation hid a `docker-ce` 29.5.3→29.7.2 upgrade three minutes before the measurement that discovered the incident — the only event-shaped evidence in the window. Same family as the `| head` that truncated evidence the day before.
- **`journalctl --list-boots` is not a reboot log.** On the VPS its earliest entry is 2026-08-10 while `uptime -s` says 2026-06-21: that gap is journal vacuuming. Reading `--list-boots` alone concludes a reboot that never happened.
- **A node that "was never in the comparison" is not covered by its conclusion.** Docker version was ruled out by pairing rpi3 against rpi4; beelink, which runs a different version entirely, was never in that pair.

**Tags:** `#docker` `#ufw` `#iptables` `#causal-test` `#confounded-control` `#evidence-truncation` `#ops-016` `#gotcha`
