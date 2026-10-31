---
id: lesson-642-a-version-floor-never-upgrades-a-controller
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, galaxy, supply-chain, security]
---

# A version floor in `requirements.yml` never upgrades a controller

**Context**: A prod `make provision NODE=rpi3` printed a deprecation warning from `authorized_key`: `ansible.module_utils._text` is removed in ansible-core 2.24. The module comes from `ansible.posix`, which `requirements.yml` declared as `>=2.0.0`.

**Problem**: The controller held `ansible.posix` 2.1.0. The upstream fix was in 2.2.0. 2.2.1 also fixed a local privilege escalation in `authorized_key` (symlink-following as root), and `ssh_hardening` runs that module with `become`. Three things kept the old version in place:
- `ansible-galaxy collection install -r` does nothing while an installed version satisfies the floor.
- `make setup-ansible` sent the install output to `/dev/null` and printed "installed" either way.
- CI caches `~/.ansible/collections` under the hash of `requirements.yml`, so it stayed on whatever resolved the last time the file changed.

The floor gave neither reproducibility nor freshness. Each controller and CI ran a different version, and none of them reported it.

**Solution** (ANSIBLE-070, #2735):
- Pin each collection to an exact version. An exact pin moves an installed older version to the pinned one with no `--upgrade` (measured in a scratch collections path).
- Enable Renovate's `ansible-galaxy` manager so the pins get bumped.
- Have `setup-ansible` show the install and fail with it.
- Make `make provision`/`make deploy` compare the controller's collections with the pins under `--require-fresh`, and refuse on a mismatch (FORCE=1 overrides).

The comparison counts every copy of a collection, because `ansible-galaxy collection list` walks its search paths as a set and cannot say which copy loads.

**Rule**: A dependency that the run environment installs once is pinned exactly, bumped by a bot, and checked at run time. A floor only says what would work, and nothing ever moves an installed version up to it.

**Tags**: `#ansible` `#galaxy` `#supply-chain` `#issue-2735`
