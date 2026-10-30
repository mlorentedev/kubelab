---
id: lesson-665-a-guard-that-must-fail-the-play-goes-before-the-roles-first-write
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ansible, handlers, lab-edge]
---

# A guard that must fail the play goes before the role's first write, so the pull it guards needs nothing rendered

**Context**: `_includes/image-pull.yml` refuses a pull that would outlast its budget behind the lab edge (#2742). It asserts before pulling, and the refusal fails the play.

**Problem**: Each role called the include after it had rendered its Compose file, because the pull ran `docker compose -f <rendered file> pull`. glances, rpi3_services and beelink_services render templates or firewall rules before that point and notify handlers from them. A refused pull would stop the play with those handlers pending. The operator's rerun would find the files already written, report no change and never fire the handlers. On rpi3 that would leave the previous Uptime Kuma allowlist rules live. A review of the DNS stack's pull found the order (#2810); no run has hit it yet (#2812). lesson-664 handles the case where nothing after the step needs it: skip the step. A pull is different, because the stack after it needs the image, so the play has to fail.

**Solution**: The include pulls the list it estimated, by name, in a loop of `docker pull` with `set -e`. It no longer reads a rendered file, so a role can run it as its first task. When the pull is refused the role has written nothing, so the rerun still sees each change the role has to make. Handlers notified by earlier roles in the same play are still pending at that point, and the refusal drops them (#2824). `tests/test_image_pull_budget.py` checks that each image a role's Compose templates fetch is in that role's pull list, because the list now replaces the compose file as the record of what the stack needs. `docker pull` prints its status on stdout, where `docker compose pull` used stderr, so the change test reads stdout for `Downloaded newer image`. agent_stack kept its order until ace2's image store was refilled (#2703). It then moved its pulls first too, in `main.yml` and `hermes.yml`, and the order guard's ledger is empty (#2812).

**Rule**: A guard that fails the play must run before the role's first write. If the guarded step reads something the role renders, have it take its input from variables instead.

**Tags**: `#ansible` `#docker` `#handlers` `#adr-075` `#issue-2812`
