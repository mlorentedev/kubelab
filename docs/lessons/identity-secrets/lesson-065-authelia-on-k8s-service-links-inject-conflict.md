---
id: lesson-065-authelia-on-k8s-service-links-inject-conflict
type: lesson
status: active
created: "2026-02-24"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia on K8s: Service Links Inject Conflicting Env Vars

**Context**: Deploying Authelia 4.39.15 on K3s. Pod entered CrashLoopBackOff immediately after start.

**Problem**: K8s auto-injects service discovery env vars for every Service in the namespace. Because the Service is named `authelia`, K8s creates `AUTHELIA_PORT_9091_TCP_PORT`, `AUTHELIA_SERVICE_HOST`, etc. Authelia treats ALL `AUTHELIA_*` env vars as configuration → `AUTHELIA_PORT_9091_TCP_PORT` maps to the deprecated `port` key → conflicts with `server.address` in config → fatal error.

**Solution**: Add `enableServiceLinks: false` to the pod spec. Also added `automountServiceAccountToken: false` since Authelia doesn't need K8s API access (the image has a read-only `/run` that prevents mounting the SA token).

**Rule**: For any application that uses its own name as env var prefix (Authelia, Vault, Consul), ALWAYS set `enableServiceLinks: false` in the K8s pod spec. Check container logs for unexpected env var warnings.

---
