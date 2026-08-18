---
id: lesson-019-caronc-apprise-oomkilled-on-k8s-cap-apprise-w
type: lesson
status: active
created: "2026-06-14"
owner: manu
tags: [kubelab, lesson]
---

# caronc/apprise OOMKilled on k8s — cap APPRISE_WORKER_COUNT, don't inherit the host-core default

**Context**: Deploying the Apprise delivery gateway (NOTIFY-001, ADR-044) as a cluster-internal `Deployment` on staging (ace1, a multi-core k3s node) with a 256Mi memory limit.

**Problem**: The pod CrashLooped — `OOMKilled` (exit 137), 4 restarts, readiness `/status` never came up (connection refused → EOF → timeout). The `caronc/apprise` (apprise-api) image runs gunicorn with `APPRISE_WORKER_COUNT` defaulting to `(2 * CPUS_DETECTED) + 1`. On a multi-core node that spawns ~9-17 workers, each loading the Apprise library, blowing past 256Mi before the app can serve `/status`. The cgroup memory limit (256Mi) is tiny relative to what the node's core count implies, so the image default is wrong for k8s.

**Solution**: Set `APPRISE_WORKER_COUNT: "2"` in the ConfigMap (the image docs explicitly recommend lowering it for lightweight use) and sized the memory limit to 384Mi for 2 workers + startup headroom. Re-applied the manifest declaratively (`kubectl apply -f`, no live-pod patching); the fresh pod reached Ready in ~20s and `/status` returned 200 OK.

**Rule**: For container images whose worker/process count auto-scales with detected CPUs (gunicorn, uwsgi, `nginx worker_processes auto`, etc.), pin the worker count explicitly in the manifest — never inherit the host-core default under a k8s memory limit. Then right-size memory to the *pinned* worker count, not the image default.
