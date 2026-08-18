---
id: lesson-069-crowdsec-acquis-yaml-cannot-be-comment-only
type: lesson
status: active
created: "2026-02-25"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# CrowdSec acquis.yaml Cannot Be Comment-Only

**Context**: Deploying CrowdSec agent on K3s. Pod entered CrashLoopBackOff immediately.

**Problem**: The `acquis.yaml` ConfigMap contained only comments (no active datasource entries). CrowdSec treats this as "no datasource enabled" and exits fatally on startup — it requires at least one active acquisition source to start.

**Solution**: Add a `filePath` datasource entry pointing to a log file path (e.g., `/var/log/traefik/access.log`) and mount an `emptyDir` volume at that path. This satisfies the startup requirement even if no logs exist yet. CrowdSec will begin processing logs once Traefik writes them.

**Rule**: `acquis.yaml` must always have at least one active (non-commented) datasource. Use a `filePath` source + `emptyDir` volume as a safe default. Empty-config startup failures are not intuitive — always check agent logs for "no datasource enabled".

---
