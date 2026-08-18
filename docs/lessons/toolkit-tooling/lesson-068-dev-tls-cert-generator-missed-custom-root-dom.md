---
id: lesson-068-dev-tls-cert-generator-missed-custom-root-dom
type: lesson
status: active
created: "2026-02-25"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Dev TLS cert generator missed custom root domains

**Context**: Bringing up the full dev stack for the first time after the cubelab→kubelab rename. `blog.kubelab.test` loaded fine but `mlorente.test` showed a cert error.

**Problem**: `*.kubelab.test` wildcards only cover one DNS level — they do not cover sibling root domains like `mlorente.test`. The cert generator (`_get_default_domains` in `toolkit/cli/tools.py`) only included `BASE_DOMAIN` + `*.BASE_DOMAIN`, ignoring the web app's domain when it uses a different root.

**Solution**: Extended `_get_default_domains` to read `APPS_PLATFORM_WEB_DOMAIN` from the env config and append it to the cert SANs if it differs from the base domain. `make regen-certs` now handles the full workflow (regenerate + reinstall CA + restart Traefik).

**Rule**: Any dev domain that doesn't end in `.$BASE_DOMAIN` must be explicitly included in the mkcert SAN. When adding new apps with custom root domains, update `_get_default_domains` or pass `--domain` to `toolkit tools certs generate`.

---
