---
id: lesson-594-a-failure-hook-with-no-memory-pages-every-run-of-a-unit-that-keeps-failing
type: lesson
status: active
title: "A failure hook with no memory pages every run of a unit that keeps failing"
created: "2026-10-18"
owner: manu
category: observability
tags: [kubelab, observability, systemd, notify, hermes]
---

# A failure hook with no memory pages every run of a unit that keeps failing

**Context**: `OnFailure=kubelab-notify@%n.service` is the fleet's one failure path, and `hermes-kubelab-vault-sync` runs every 15 minutes.

**Problem**: The notifier knew nothing about the previous run, so when the sync broke on 2026-10-17 (#2417) it paged on every run: more than 100 entries in a day, each as loud as the first, and any different alert arriving meanwhile was buried.

**Solution**: The notifier keeps `count first last` per unit in `/var/lib/kubelab-notify`. The first failure pages, a reminder with the count follows hourly, and a unit that declares `OnSuccess=kubelab-notify-recovered@%n.service` sends one recovery page and clears the state. The delivery time is recorded only after the send succeeds, so a page that never arrived does not silence the next. A state older than six hours starts a new incident, so a unit with no recovery hook never reports an old count. `tests/test_node_notify_dedup.py` runs the shipped script against shims for `systemctl`, `journalctl` and `curl` and counts the requests.

**Rule**: A hook that fires on an event needs the state of the incident it belongs to, or its volume is the failure's frequency. Prefer reporting every state change once over silencing retries (`StartLimit*` stops the work and hides the failure). When the recovery signal needs a newer systemd than every node has (`OnSuccess=` is 249; the oldest nodes run 237), wire it only where it exists and let the TTL cover the rest.

**Tags**: `#systemd` `#notify` `#pr-2423`
