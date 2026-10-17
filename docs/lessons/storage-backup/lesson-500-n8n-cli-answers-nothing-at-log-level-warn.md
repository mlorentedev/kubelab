---
id: lesson-500-n8n-cli-answers-nothing-at-log-level-warn
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, n8n, restore-drill, memory]
---

# n8n's CLI answers nothing, with exit 0, at `N8N_LOG_LEVEL=warn`, and in its pod it costs a second n8n

**Context**: BACKUP-068 needed the workflow ids live has, to check the Authelia and
n8n restore drill against. The first idea was the app's own CLI in the live pod:
`kubectl exec deploy/n8n -- n8n list:workflow`.

**Problem**: Two separate things, both measured on prod on 2026-10-01.

- The command printed one line, a Sentry notice, and exited 0. `n8n list:workflow`
  and `n8n export:workflow` write their answer through n8n's logger, not stdout, and
  the pod sets `N8N_LOG_LEVEL=warn`. The same command with `N8N_LOG_LEVEL=info` lists
  all four workflows. A check that read the first answer would have reported zero
  workflows, or passed with nothing compared (lesson-416).
- Every `n8n` command starts a full second n8n process inside the container. The pod
  was at 365Mi of its 512Mi limit, so each probe could have OOM-killed the live
  automation server. This is the same mechanism as OPS-033 (#1902) for imports.

**Solution**: The drill reads live the way the capture does: `sudo -n sqlite3
-readonly -json` on the database file on the VPS, over SSH, with the PV's path
resolved from `kubectl get pv`. That puts no load on the pod. It also gave a
stronger check than the CLI could, because the same SQL runs against live and
the restore. Every durable row live had at snapshot time must be restored by id,
and an Authelia opaque identifier must also come back unchanged (compared as a digest).

**Rule**: To read an app's live state for a check, read its data the way the backup
does, not by running the app a second time inside its own memory limit. When a
CLI's output depends on a log level, set the level explicitly, and treat an empty
answer as CANNOT CHECK.

**Tags**: `#n8n` `#restore-drill` `#backup-068` `#ops-033`
