---
id: lesson-361-ci-green-is-not-the-same-claim-as-this-runs-on-real-hardware
type: lesson
status: active
created: "2026-08-21"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, ansible-provisioning, testing]
---

# CI green is not the same claim as "this runs on real hardware"

**Context**: BACKUP-044 Part 3 (#1179) merged the `node_backup` role — CI green,
`make lint-ansible` passing, 27 unit tests passing. None of that exercises
`ansible-playbook` against a real host; the tests render Jinja templates and
assert on the text. `make backup ENV=prod` was not run again until Part 4,
days later, to measure real capture/ship timing for a scheduling decision.

**Problem**: The first real deploy to all four prod nodes surfaced three
failures, one per node class, in order:

1. **rpi3 and rpi4**: `apt install sqlite3` failed, "No package matching
   'sqlite3' is available" — the task never called `update_cache`, so a cold
   apt index (present on these two, not on VPS/Beelink by chance) failed
   closed instead of refreshing.
2. **rpi4 only**: restic install failed, `bunzip2: not found` — the image
   doesn't carry it, and its installed `libbz2-1.0` build no longer matches
   the configured repo's candidate, so `apt install bzip2` would have failed
   too on an unrelated dependency conflict.
3. **All four nodes**: the ship unit failed *after* successfully creating the
   R2 repository — restic's own "unable to locate cache directory: neither
   $XDG_CACHE_HOME nor $HOME are defined". A oneshot systemd service with no
   `User=` has no `$HOME` unless the unit declares one; nothing in review,
   lint, or the unit tests renders a unit and starts it under `systemd`.

None of the three is a logic bug a template-render test could catch — they
are all "does the target environment actually have what this assumes", which
only shows up by running the thing where it runs.

**Solution**: Fixed per-node, deployed, and re-verified by a real
`systemctl start` capture+ship cycle on all four nodes after each fix (see
`specs/BACKUP-044-critical-subset-pipeline/verification.md`'s Part 4 evidence
section, and kubelab#1200). `update_cache: true` / `cache_valid_time: 3600`
matching the existing convention (`base_system`, `dev_node`); restic's
decompress step moved from shelling out to `bunzip2` to Python's stdlib `bz2`
module, since every Ansible-managed node already guarantees a `python3`
interpreter and this removes the host dependency instead of chasing rpi4's
specific package conflict; `Environment=HOME=/root` on the ship unit.

**Rule**: A role's test suite proves the role is internally consistent, not
that it works. Lint and unit tests answer "does this Jinja render the string
I expect" — they cannot answer "does this node have `bzip2`", "is this apt
cache fresh", or "does this systemd unit have a `$HOME`", because those
questions only exist once something actually executes on the target. A
role that has never been run against its real target should be treated as
unverified regardless of how green its CI is, and the gap closes only by
running it there — ideally before merge, but if not then, at the first
opportunity afterward rather than whenever a change happens to need the
deploy anyway.

**Tags**: `#ansible` `#testing` `#pr-1179` `#pr-1200` `#pr-1201`
