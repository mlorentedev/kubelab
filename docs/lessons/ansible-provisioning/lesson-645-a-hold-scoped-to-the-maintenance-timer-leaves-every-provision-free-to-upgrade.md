---
id: lesson-645-a-hold-scoped-to-the-maintenance-timer-leaves-every-provision-free-to-upgrade
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, apt, docker, ci]
---

# A hold scoped to the maintenance timer leaves every provision free to upgrade

**Context**: BuildKit sessions on the Beelink began dropping on 2026-10-27, and a Gitea job hung for three hours. That morning `docker-ce` had moved from 29.8.1 to 29.9.2. The ticket (#2722) blamed `node_maintenance`, which "runs dist-upgrade on the platform node". **Correction (2026-10-29):** the hung job was not the engine. It was pulling a 2.31 GB base layer at about 80 KB/s when the runner's timeout cancelled it, and the session lines appear on builds that pass too (#2722). The hold below stands as policy: the engine moves on purpose, not as a side effect.

**Problem**: The timer could not have done it. It upgrades from the security pocket only, and it holds `docker-ce`, `docker-ce-cli` and `containerd.io` for its run. The upgrade came from `base_system`'s "Upgrade all packages" (`apt upgrade: dist`), which every `make provision` runs. The protection existed, but only on the path that did not need it. The role's own comment named provision as the place where Docker is "patched deliberately". Nothing made it deliberate: a provision run for any other reason moved Docker too.

The Beelink's apt history named the caller:

```
Start-Date: 2026-10-27  03:32:30
Commandline: /usr/bin/apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -o DPkg::Lock::Timeout=60 dist-upgrade
Requested-By: manu (1000)
```

`DPkg::Lock::Timeout=60` is the Ansible `apt` module's default `lock_timeout`, so the line is a play, not the timer and not `unattended-upgrades`.

**Solution** (#2722):

- `base_system` holds a node's `base_system_held_packages` before its upgrade. The Beelink's play lists the CI engine.
- `base_system_release_holds=true` releases them for one run and holds them again after it.
- The hold reads `package_facts` first, because `dpkg_selections` fails on a package dpkg has never seen. That is every one of them on a node's first provision.
- The hold cannot live in the `docker` role: it runs after `base_system`, so the first provision would upgrade first and freeze the result.

**Rule**: Before deciding where a package hold goes, find every path that upgrades the package, and place the hold ahead of the first one. To find the caller of an upgrade that already happened, read `/var/log/apt/history.log`. `Commandline` and `Requested-By` name it, and Ansible's `apt` module leaves its lock timeout in the command line.

**Tags**: `#apt` `#docker` `#ansible` `#issue-2722`
