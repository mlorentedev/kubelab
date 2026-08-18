---
id: lesson-250-rotated-syslog-files-un-gzipped-consume-200mb
type: lesson
status: active
created: "2026-05-10"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Rotated syslog files (un-gzipped) consume 200MB+ on busy nodes — maintain role missed it

**Context:** During aws1 RELIAB-009 incident response: diagnosed disk at 96% after Helm upgrade pull. `du -sh /var/log/*` showed `/var/log/syslog.1` = 201MB (single un-rotated current archive) plus `syslog.2.gz` 22MB, `syslog.3.gz` 12MB, `syslog.4.gz` 3.1MB — 238MB total. The 201MB syslog.1 came from a 20-minute window when K3s server was in a futex deadlock spamming `Sending HTTP/1.1 502 response to 127.0.0.1:NNNN: dial tcp 10.42.0.6:10250: connect: connection refused` every millisecond.
**Problem:** The `node_maintenance` Ansible role only handles `journalctl --vacuum-size=20M` (covers systemd journal). It does NOT touch the classic rsyslog-rotated files in `/var/log/syslog.*`, `/var/log/kern.log.*`, `/var/log/auth.log.*`. On Ubuntu with rsyslog, logrotate rotates these daily and keeps 7 copies (default `/etc/logrotate.d/rsyslog`). A pathological burst (futex deadlock spamming syslog) can fill the active syslog file to hundreds of MB BEFORE logrotate's nightly cron rotates it. Result: a low-disk node (8GB EBS) goes from healthy to disk-pressure in minutes, and maintain.yml can't recover it.
**Solution:** Extend the `node_maintenance` Ansible role with a task that prunes rotated log files older than N days (parametrized; default 3): `find /var/log -maxdepth 1 -regex '.*\.(log\.|[0-9]).*' -mtime +{{ rotated_log_retention_days }} -delete` (idempotent). Also consider configuring rsyslog/logrotate to enforce maximum file size before rotation (`size 50M` in /etc/logrotate.d/rsyslog) so a runaway logger can't bloat the active file. Add a separate task to truncate the ACTIVE syslog if it exceeds a threshold (defensive): `find /var/log -maxdepth 1 -name 'syslog' -size +100M -exec truncate -s 0 {} \;`. Document that node_maintenance should run BEFORE high-disk-impact operations (Helm upgrade, image pulls) not just on a weekly timer.
**Tags:** `#ansible` `#node_maintenance` `#syslog` `#rsyslog` `#logrotate` `#ubuntu` `#disk-pressure` `#automation` `#gap`
