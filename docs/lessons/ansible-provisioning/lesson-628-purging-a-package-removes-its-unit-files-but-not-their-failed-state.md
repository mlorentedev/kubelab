---
id: lesson-628-purging-a-package-removes-its-unit-files-but-not-their-failed-state
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, systemd, teardown, idempotence, vps]
---

# Purging a package removes its unit files but not their failed state, so `systemctl --failed` keeps listing them

**Context**: OPS-047 (#2701) retired certbot and nginx from the VPS. Two retired designs had left them installed; every certificate had expired and `certbot.service` failed every 12 hours. The acceptance criterion was that `systemctl list-units --failed` no longer lists `certbot.service`, so the role's teardown was written to purge the packages and nothing more.

**Problem**: purging is not enough. In a booted Ubuntu 24.04 container that reproduced the VPS (certbot, its Cloudflare and nginx plugins, nginx, a renewal config that makes the unit fail), `apt-get purge` left both units listed as `certbot.service not-found failed failed` and `certbot.timer not-found failed failed`. A throwaway user unit showed the same: deleting the unit file and reloading turns `loaded failed` into `not-found failed`, and `systemctl stop` does not clear it. systemd keeps a failed unit until something resets it (`CollectMode=inactive` never collects a failed one), whether or not its file still exists.

Two smaller findings from the same run. `reset-failed` exits 0 whether or not anything matches, so an unconditional task reports `changed` on every run and the second run can never be `changed=0`. And `apt remove nginx` does not take `nginx-common` along on Ubuntu 24.04: noble-updates 1.24.0-2ubuntu7.19 no longer lists nginx in its dependencies (the release pocket still did), so it stayed installed with `/etc/nginx` until it was named in the purge list.

**Solution** (#2701): the `headscale` role purges the packages, removes `/etc/letsencrypt`, then reads `systemctl list-units --failed 'certbot*'` (`check_mode: false`, `changed_when: false`) and runs `systemctl reset-failed 'certbot*'` only when the read found one. Against the container: first run `changed=2` (the purge and the reset), second run and `--check` both `changed=0`, and afterwards no dpkg row, no unit file, no failed unit. `tests/test_headscale_legacy_tls_teardown.py` holds the package list, the directory removal, the privilege each task needs (the VPS play has no play-level `become`), the reset's gate and that no other role installs a purged package.

**Rule**: a teardown that has to leave the host's health view clean needs `reset-failed` after the removal, gated on a read of the failed list so it stays idempotent. Measure "no longer listed" on a booted systemd (a container started with `/sbin/init`, `--privileged --cgroupns=host`), because the package's maintainer scripts and the unit file say nothing about the failed state. When the target is an apt package pair that depends on each other, read the dependency metadata for the version the host installs, not the release pocket.

**Tags**: `#ansible` `#systemd` `#teardown` `#idempotence` `#issue-2701`
