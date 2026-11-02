---
id: lesson-638-a-guard-scoped-to-one-stack-leaves-its-defect-open-in-every-other-role
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, images, supply-chain, coredns, pihole]
---

# A guard scoped to one stack leaves its defect open in every other role

**Context**: Reading the `coredns` role for DNS-007 (#2716), which restarts Pi-hole, the LAN's resolver on the RPi4 edge.

**Problem**: The role ran `pihole/pihole:latest` and pulled it on every deploy, with `changed_when: false` on the pull. Any `make deploy TARGET=dns` could move the resolver to an image nobody chose, and the run would report nothing. The container on the edge had been recreated that night. The defect had been fixed once already, for the Beelink's runner image (#2033), but its test reads only `provision-bee.yml`, so it was fixed in one stack and stayed open in every other one.

**Solution**: Pin the tag to the digest the edge already ran (`2026.10.0`, the same manifest as `latest` on 2026-10-27, checked with `docker buildx imagetools inspect`, so the pin changes nothing on the node). Add `tests/test_ansible_role_images_versioned.py`, which checks every `*_image` default of every role and every `image:` line in role templates. The version predicate now lives in `tests/image_versions.py`, shared by both checks.

**Rule**: When a guard closes a defect class, scope it to the class (every role, every template), not to the instance that was found. A per-stack guard is a record of where the defect was, not proof that it is gone.

**Tags**: `#images` `#coredns` `#pr-2716`
