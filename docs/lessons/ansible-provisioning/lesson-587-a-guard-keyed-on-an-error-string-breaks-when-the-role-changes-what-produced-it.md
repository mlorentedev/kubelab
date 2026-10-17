---
id: lesson-587-a-guard-keyed-on-an-error-string-breaks-when-the-role-changes-what-produced-it
type: lesson
status: active
created: "2026-10-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, apt, node-maintenance, guards]
---

# A guard keyed on an error string breaks when the role itself changes what produced the string

**Context**: `make maintain NODE='all:!jetson' ENV=prod` exited 0 on 2026-10-17 and skipped security
patching on beelink, gcp1 and rpi3. Each node reported it "could not hold" the Docker packaging it
does not run: `docker.io`/`containerd` on beelink, `docker-ce`/`docker-ce-cli` on gcp1 (#2406).

**Problem**: `node_maintenance` decided whether a failed `apt-mark hold` mattered by matching apt's
stderr for `Unable to locate package`, the text measured on beelink on 2026-08-22. That measurement
was taken with APT lists present. The role deletes `/var/lib/apt/lists` at the end of every run,
and the Ansible path places its holds before the upgrade task refreshes them. Measured in
`ubuntu:24.04` for a package removed with its config files kept (dpkg state `config-files`):

```
lists present  apt-mark hold logrotate -> rc=0    "logrotate set on hold."
lists absent   apt-mark hold logrotate -> rc=100  "Can't select installed nor candidate version ..."
```

A package that was never installed still says `Unable to locate package` without lists, so the
first measurement looked general. Leftovers from a Docker packaging switch are `config-files`
packages, so the guard read them as installed packages it could not protect, and skipped the patch.

**Solution**: read "installed" from dpkg, which needs no lists:
`dpkg-query -W -f='${Package} ${db:Status-Status}\n' <held list>`. Only installed packages are held,
so any non-zero rc from a hold now means a running package is unprotected. Both implementations
changed (the Ansible tasks and the timer's `kubelab-maintenance.sh`), and
`tests/test_node_maintenance_patching.py` fails if either matches apt's text again.

**Rule**: before keying a guard on a tool's message, list the states that change the message. If the
same role changes one of those states, the measurement holds only for the first run. Ask the tool
for its state (`dpkg-query`, `systemctl is-active`, an exit code), not for an error message.

**Tags**: `#apt` `#node-maintenance` `#issue-2406`
