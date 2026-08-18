---
id: lesson-252-persistent-journald-on-debian-rpi-needs-99-dr
type: lesson
status: active
created: "2026-05-11"
owner: manu
tags: [kubelab, lesson, ansible, journald, systemd, drop-in, raspberry-pi, debian, gotcha, iac-pattern]
---

# Persistent journald on Debian RPi needs 99- drop-in AND post-restart flush

**Context:** ANSIBLE-023 (2026-05-11): forcing `Storage=persistent` on rpi3 via `/etc/systemd/journald.conf.d/00-kubelab.conf` after the same-day outage that lost all crash forensics because journald was volatile.
**Problem:** Two independent failure modes stacked: (1) After applying the drop-in and restarting `systemd-journald`, `journalctl --header` still reported journals at `/run/log/journal/...` and `/var/log/journal/<machine-id>/` stayed empty. `systemd-analyze cat-config systemd/journald.conf` revealed Debian RPi images ship `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` with `Storage=volatile` (deliberate, to spare SD card life). systemd merges drop-ins **lexicographically across `/etc` and `/usr/lib` as one set**, so `00-kubelab.conf` from `/etc/` loses to the system's `40-` from `/usr/lib/`. (2) After renaming to `99-kubelab.conf` (which now wins), `journalctl --header` STILL pointed at `/run/log/journal/...`. The `restart systemd-journald` Ansible handler re-reads config but does not migrate the active journal file from `/run` to `/var` — that migration is a separate operation.
**Solution:** Both gotchas have a deterministic fix. (1) **Use `99-` prefix for any `/etc/systemd/*.conf.d/` drop-in that must override a vendor default on Debian RPi images.** The drop-in precedence model is "highest filename wins regardless of directory." Concretely: `99-kubelab.conf` in `/etc/systemd/journald.conf.d/` beats `40-rpi-volatile-storage.conf` from `/usr/lib/`. Verify with `systemd-analyze cat-config systemd/journald.conf` — the merged view shows each contributing file in order; the last `Storage=` line wins. (2) **`restart systemd-journald` is not sufficient; pair it with `journalctl --flush`.** Restart opens new journal files but does not move existing volatile state to the persistent path. In Ansible, chain two handlers: `restart systemd-journald` then `flush journald to persistent storage` (command: `journalctl --flush`, `changed_when: false`). Notify both from the config-template task. After this combo, the persistent dir starts populating immediately and `journalctl --disk-usage` reports a value matching `/var/log/journal/<machine-id>/`. Generalisable: any systemd unit with a vendor drop-in default on RPi/Debian (network, resolved, etc.) probably needs the same `99-` strategy. Always cross-check with `cat-config`, never assume `/etc/` always wins.
**Tags:** `#ansible` `#journald` `#systemd` `#drop-in` `#raspberry-pi` `#debian` `#gotcha` `#iac-pattern`
