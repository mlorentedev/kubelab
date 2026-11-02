---
id: lesson-625-a-plugin-traefik-downloads-at-start-is-a-dependency-on-the-network-at-every-boot
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, traefik, plugins, boot]
---

# A plugin Traefik downloads at start is a dependency on the network at every boot

**Context**: Traefik's CrowdSec bouncer and `api-key` were remote plugins (`experimental.plugins`), so Traefik downloaded both from `plugins.traefik.io` every time a pod started. The lab moved site behind a new edge (NET-005), and ace1 booted while the edge was not yet serving a default route.

**Problem**: K3s refused to start without a default route and retried for 22 hours (16 080 restarts). The route appeared at 00:51:47Z, K3s started, and Traefik tried the download at 00:52:04Z, before egress was usable. Traefik logged `Plugins are disabled because an error has occurred ... unable to download plugin api-key` and started anyway, with every plugin off. Each router whose chain names `crowdsec-bouncer` was then dropped as `invalid middleware ... does not exist`, so every protected staging host answered 404. The pod was Ready, Argo CD reported Synced/Healthy, and nothing alerted. The same happened on 2026-10-20 (#2565) and earlier in another form (lesson-216). Prod carries the same dependency: a prod Traefik restart while plugins.traefik.io is unreachable takes down every protected public route.

**Solution**: The plugins are local plugins. The `k3s_server` role fetches each source at provision time, when egress is a precondition anyway, from the module's GitHub tag archive, verified against a pinned sha256, into one directory per version (`k3s_traefik_local_plugins`). The HelmChartConfig mounts it with `type: hostPath`, so a start downloads nothing. `abortOnPluginFailure: true` turns a plugin that still fails to load into a pod that does not start, which the chart's rolling update (`maxUnavailable: 0`) keeps from replacing a healthy one. `tests/test_traefik_offline_start.py` asserts the rendered config, the pins, and that every plugin a Middleware uses is loaded.

**Rule**: Anything a server fetches when it starts makes the network a precondition of every restart, and restarts happen exactly when the network is in doubt (a boot, a site move, an outage). Fetch at provision time, pin by hash, and load from disk. And when the software's own failure mode is "degrade silently", choose the setting that fails loudly instead.

**Tags**: `#traefik` `#plugins` `#boot` `#issue-2565`
