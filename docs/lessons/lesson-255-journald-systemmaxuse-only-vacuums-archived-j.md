---
id: lesson-255-journald-systemmaxuse-only-vacuums-archived-j
type: lesson
status: active
created: "2026-05-12"
owner: manu
tags: [kubelab, lesson, journald, logrotate, ansible-024, systemd, prod]
---

# journald SystemMaxUse only vacuums archived journals — active journal can briefly exceed cap

**Context:** ANSIBLE-024 propagation to kubelab-vps (Hetzner Cloud, prod K3s). After applying `base_system` role with `Storage=persistent` + `SystemMaxUse=20M` drop-in and restarting systemd-journald, `journalctl --disk-usage` reported 24.0M — 4M over the configured cap.
**Problem:** First reaction was to suspect the cap wasn't being honored. Tried `sudo journalctl --vacuum-size=20M` to force-trim, but it freed 0B from `/var/log/journal/<machine-id>`, `/var/log/journal`, and `/run/log/journal`. Other 5 nodes in the same rollout (aws1/rpi4/beelink/ace1/ace2) were all comfortably under 20M, so the cap clearly worked there — why not on VPS?
**Solution:** `SystemMaxUse` only governs the total size of **archived** (sealed/rotated) journal files. The **active** journal file (the one journald is currently writing to) grows until it hits journald's internal rotation threshold (~`SystemMaxFileSize`, default 1/8 of `SystemMaxUse` rounded up to file-system block boundaries, or 64MB max). When journald rotates the active file, it becomes archived, and then `SystemMaxUse` is enforced against the new archived set. So a freshly-restarted journald on a busy host can legitimately show usage above `SystemMaxUse` for hours/days until the first rotation. `--vacuum-size` confirms this — it returns 0B freed because there are no archived journals yet, all the bytes are in the still-active file. Action: do not panic. Either wait for natural rotation, or force with `systemctl kill -s SIGUSR2 systemd-journald` (intrusive on prod, brief interruption to logging). For ANSIBLE-024 acceptance, treat 24M post-restart as PASS and revisit on next maintenance window.
**Tags:** `#journald` `#logrotate` `#ansible-024` `#systemd` `#prod`
