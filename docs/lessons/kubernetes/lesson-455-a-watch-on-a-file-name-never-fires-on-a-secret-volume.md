---
id: lesson-455-a-watch-on-a-file-name-never-fires-on-a-secret-volume
type: lesson
status: active
created: "2026-09-24"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, authelia, secrets]
---

# A file watch keyed on the file's name never fires on a Secret volume, so "no restart needed" was never true

**Context**: AUTH-004 added `manu` to Authelia. `make apply-secrets ENV=staging`
reported `secret/authelia-users configured` at 00:32:22, and a minute later the
file inside the pod listed `manu`. CLAUDE.md said the users file is mounted as a
directory with `watch: true`, so Authelia reloads it with no restart.

**Problem**: Authelia kept answering `user not found` for `manu` (Loki,
`{container="authelia"}`, 00:35:05). The user took it for a mistyped password.
Authelia 4.39.15's watcher (`internal/service/file_watcher.go:79-84`, `:132`)
watches the file's directory and drops every event whose basename is not the
file's. The kubelet updates a Secret volume atomically: it writes a new
`..<timestamp>` directory and swaps the `..data` symlink.
`users_database.yml` is a symlink into `..data` and is never touched; its mtime
was still the pod's start time. No event carries the watched name, so the
reload never runs. The claim was written from the config, never measured.

**Solution**: #1804. `apply-secrets` notes every Secret kubectl reports
`configured` or `created`, reads the live pod templates for workloads that
reference it (env `secretKeyRef`, `envFrom`, `secret` and projected volumes),
and rollout-restarts each one, waiting for it to become ready. `unchanged`
triggers nothing, so a re-run stays a no-op. A failed restart fails the
command. The consumers are derived, not listed, which also covers every
env-var consumer: those read a Secret once, at start, whatever anyone says.

**Rule**: A Secret is not live until what reads it has re-read it. Do not trust
an app's "watch" on a Secret-mounted file until the reload has been seen after
a real update, in its logs. A watch on the directory for the file's name is the
common shape, and it cannot work with the kubelet's symlink swap.

**Tags**: `#authelia` `#secret-volume` `#fsnotify` `#issue-1804` `#auth-004`
