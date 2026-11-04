---
id: lesson-708-an-ingress-memory-ceiling-measured-turned-out-to-be-cpu
type: lesson
status: active
title: "An ingress memory ceiling, measured, turned out to be CPU"
created: "2026-11-04"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, traefik, load-test]
---

# An ingress memory ceiling, measured, turned out to be CPU

**Context**: Once Traefik had 1,536 MiB and probes that tolerate saturation (lesson-698, lesson-701), it reached 1,328 MiB at 2,000/s in staging. #3057 assumed that nothing bounding its connections meant memory would hit the limit past 2,000/s, and proposed a cap.

**Problem**: Measured on 2026-11-04 at 2,000/s and 3,200/s, with the rate limiter bypassed, the edge never reached its memory limit. It ran out of CPU first. Traefik used 3.4 to 3.8 of the node's 4 cores, delivered about 1,100 to 1,300/s whatever was offered, and timed everything else out at 5 s. At 3,200/s it was restarted by liveness, not OOMKilled. Its memory peaked at 1,445 MiB (94%) and the samples after each restart read low, so they show a reset, not headroom. A connection cap would have bounded the wrong resource. It was also unnecessary: prod's limiter admits 30/s per host, so in-flight per host stays near 300 even with 5 s stalls. The same rerun replaced the 2,000/s results on disk, because the tool named files `<date>-<commit>` and both runs shared both.

**Solution**: #3057 closed with no change to Traefik, and the report records the CPU ceiling and why prod cannot reach it. The load-test tool now names a rerun `-2`, `-3` instead of overwriting, tested in `tests/test_load_test.py`.

**Rule**: Before bounding the resource a projection says will run out, push the load past that point and read what actually fails. In-flight requests are rate × latency, so check what bounds the rate upstream before adding a cap downstream. A result file named only by date and commit is not unique: two runs of one commit on one day collide.

**Tags**: `#traefik` `#load-test` `#issue-3057`
