---
id: lesson-659-a-fix-that-relaxes-what-one-check-needs-takes-away-the-coverage-another-got-from-it
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: observability
tags: [kubelab, observability, edge, networking]
---

# A fix that relaxes what one check needs takes away the coverage another got from it

**Context**: B14's hard-reset test on the lab edge (NET-005, #2661). After T4, the switch cable goes back in and `make edge-boot-check` runs with no case.

**Problem**: The check read 27 of 27 `OK`, exit 0. Minutes later the edge's `eth0` read `NO-CARRIER`: the switch was off. The script defined `has_carrier` and never called it. Until #2732 it had not needed to: the LAN address needed a carrier, so a missing cable failed `LAN address on eth0`. #2769 gave the address `ignore-carrier`, which is right for DNS. From then on the address, its route and the DNS answer on it all held without a cable, and nothing in the default case read the cable. The fix was correct, and nothing failed when the coverage went.

**Solution**: Every case but `no-lan` now has its own `eth0 has a carrier` line (#2800). `tests/test_edge_boot_check.py` asserts that a healthy boot prints it, and that a cable that is out fails it and nothing else, with or without the uplink.

**Rule**: Before relaxing a precondition, list the checks that pass or fail on it. If one of them was the only signal for something else, here the cable, give that thing its own line in the same change. A check whose every line reads `OK` proves only what the lines read.

**Tags**: `#observability` `#edge` `#pr-2804`
