---
id: lesson-696-a-load-tests-limit-can-be-a-limit-nobody-declared
type: lesson
status: active
created: "2026-11-02"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, load-test, traefik, limitrange]
---

# A load test's limit can be one nobody declared, and the crash loop it starts reads as low capacity

**Context**: OPS-054 ramped k6 against staging to find where the platform degrades, expecting CPU at the 500m pod limit.

**Problem**: At about 1,600 requests per second, errors passed 80% while the node sat at 25-65% CPU with 8 GB free, and `api` never restarted. Traefik was OOMKilled at 384 MiB. Its Deployment declares no resources: the limit came from the `kube-system-defaults` LimitRange, so `kubectl get deploy` showed `{}` and only the pod's spec showed the number. Then the next ramps read as `web` failing at 50 requests per second, which was Traefik in CrashLoopBackOff.

**Solution**: A step now records the edge's restarts and reports `edge-restart`, and the run waits for the edge to stay up 120 s before the next ramp. With that, six ramps gave a real range, 1,200 to 2,000 requests per second. Filed as #2975.

**Rule**: Read limits from the running pod, never the Deployment, because admission may have added them. A load test also needs a health check on everything in the path, not only on its target: the component that fails is the one you were not watching, and everything measured after it reflects its recovery, not capacity.

**Tags**: `#load-test` `#limitrange` `#traefik` `#issue-2956` `#issue-2975`
