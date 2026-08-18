---
id: lesson-254-ubuntu-etc-logrotate-d-rsyslog-groups-6-syslo
type: lesson
status: active
created: "2026-05-12"
owner: manu
tags: [kubelab, lesson, ansible, logrotate, rsyslog, regex, ubuntu, idempotence]
---

# Ubuntu /etc/logrotate.d/rsyslog groups 6 syslog paths into ONE block — regex must match multi-path stanza

**Context:** ANSIBLE-025 validation on aws1 (Ubuntu 24.04). Replacing the buggy `lineinfile` `insertafter: '^/var/log/syslog$'` in `base_system` role with `ansible.builtin.replace` to inject `size 50M` INSIDE the logrotate block. Initial regex proposal: `(^/var/log/syslog\n\{\n)(?!\s*size\s)`.
**Problem:** First apply on aws1 reported `ok=11 changed=6` but BOTH the Scrub and Cap tasks were among the `ok=`, not `changed=`. The Cap regex silently no-opped. Investigation via `ssh aws1 "grep -A 10 '^/var/log/syslog$' /etc/logrotate.d/rsyslog"` revealed Ubuntu's stock rsyslog config groups SIX paths under ONE `{ ... }` block: `/var/log/syslog`, `/var/log/mail.log`, `/var/log/kern.log`, `/var/log/auth.log`, `/var/log/user.log`, `/var/log/cron.log` — only THEN comes the `{`. The mental model "one path per block" baked into the ticket text + the proposed regex shape (path immediately followed by `\n{\n`) does not match real-world Ubuntu/Debian logrotate layouts. The grep -A4 acceptance criterion from the original ticket also reflected this wrong assumption (4 lines wasn't enough to reach the block on Ubuntu).
**Solution:** Rewrite the regex to capture the WHOLE path group containing `/var/log/syslog` up to and including the opening brace: `(^(?:/var/log/\S+\n)*?/var/log/syslog\n(?:/var/log/\S+\n)*\{\n)(?!\s*size\s)` with replacement `\1    size {{ rsyslog_logrotate_size_cap }}\n`. Lazy quantifier `*?` before the syslog anchor handles paths listed before syslog; greedy `*` after handles paths after. The negative lookahead `(?!\s*size\s)` preserves idempotency. Validated end-to-end on aws1: first apply `changed=1` on Cap (Scrub `ok` because no prior contamination), `grep` confirms `size 50M` is the first directive after `{`, third apply `changed=0` across all 11 logging tasks. Also adjusted the Scrub regex from `(^/var/log/syslog\n)\s*size\s+\S+\n(\{)` → `(^/var/log/syslog\n)\s*size\s+\S+\n` to handle the real-world contamination shape (mis-inserted line lands between paths, not between syslog and `{`).
**Tags:** `#ansible` `#logrotate` `#rsyslog` `#regex` `#ubuntu` `#idempotence`
