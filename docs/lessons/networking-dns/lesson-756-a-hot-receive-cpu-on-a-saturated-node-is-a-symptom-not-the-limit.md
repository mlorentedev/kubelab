---
id: lesson-756-a-hot-receive-cpu-on-a-saturated-node-is-a-symptom-not-the-limit
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns, load-test, softirq, rps, udev]
---

# A hot receive CPU on a saturated node is a symptom, not the limit

**Context**: Under the load test, `web` on ace1 degraded at 3,200/s with one CPU (`cpu2`) at 99.5% busy, most of it softirq. ace1's network card (`r8169`) has one receive queue and one interrupt vector, so every receive softirq lands on the interrupt's CPU. Receive packet steering (RPS) was the obvious fix: set `rps_cpus` on `rx-0` to every CPU and let the kernel spread the protocol work (#3375).

**Problem**: Two things turned out to be true.

1. Steering spread the work (`cpu2`'s softirq fell from 60 to 44 to 46% at 2,000/s), but it did not raise the limit: the one steering-on step at 3,200/s served 1,722/s with p50 492 ms, against 1,767 to 2,116/s and 400 to 449 ms in three steering-off steps on another build. The node had already used 3.85 to 3.90 of its 4 cores without steering, and reached 3.98 with it. One CPU at 100% was the most visible part of a full node, not a wall the other CPUs were idle behind. The driver's poll also stays on the interrupt's CPU, since RPS only moves the protocol work after it.
2. The first udev rule to set the mask never applied. It matched `SUBSYSTEM=="queues"`, but a queue object (`/sys/class/net/<if>/queues/rx-N`) has no `uevent` file: udev never sees an event for it, and `udevadm test` answers "No such device". The provision's read-back assert caught it (`reads ['0'], not f`).

**Solution**: Steering was turned back off through the role's off path (apply changed=2, rerun changed=0, every `rps_cpus` reads `0`) and the role change was not merged. The report records the before/after (`docs/load-test/report-2026-11-02.md`, "Spreading it does not raise the limit"). For the udev part, the working form matches the net device and writes the masks itself: `ACTION=="add", SUBSYSTEM=="net", KERNEL=="<if>", RUN+="/bin/sh -c 'for q in /sys/class/net/%k/queues/rx-*/rps_cpus; do echo <mask> > $q; done'"`.

**Rule**: Before spreading a hot CPU's work, read the node's total. If the node is near its core count at the same step, spreading moves load, not the limit, and the fix is less work or more cores. A tuning change that measures as no gain is reverted, not merged as an unused setting. To set a per-queue sysfs value from udev, match the net device and write the queue files in `RUN`, and assert the value read back, because a rule that never fires fails silently.

**Tags**: `#load-test` `#rps` `#udev` `#issue-3375`
