---
id: lesson-209-traefik-plugins-can-t-mount-secrets-cross-nam
type: lesson
status: active
created: "2026-03-26"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Traefik plugins can't mount Secrets cross-namespace

**Context**: Migrating CrowdSec bouncer from ForwardAuth sidecar to native Traefik plugin (SEC-003).

**Problem**: Plugin reads API key via `crowdsecLapiKeyFile` from a volume mount. Traefik runs in `kube-system`, but the bouncer Secret lived in `kubelab`. K8s pods can only mount Secrets from their own namespace.

**Solution**: Duplicate the Secret in `kube-system` (`crowdsec-bouncer-traefik`). Added `namespace` field to `SecretMapping` dataclass so `apply-secrets` handles cross-namespace secrets generically. Precedent: `cloudflare-api-token` already follows this pattern.

**Rule**: When a workload in one namespace needs a secret from another, duplicate the Secret via toolkit (not reflector/replicator). Add a `SecretMapping` with explicit `namespace`. Keep the original Secret too if other consumers need it (e.g., LAPI postStart hook in `kubelab` still uses `crowdsec-bouncer`).
