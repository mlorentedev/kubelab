---
id: "lesson-568-a-reference-copy-of-a-secret-is-a-second-store"
type: lesson
status: active
title: "A \"reference copy\" of a secret is a second store"
created: "2026-10-14"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, sops, authelia, oidc]
---

# A "reference copy" of a secret is a second store

**Context**: The Authelia OIDC signing key lives in SOPS, and K8s Authelia
serves it from there. A gitignored `infra/config/secrets/{env}.oidc-jwks.pem`
sat beside it. `toolkit secrets jwks` wrote that file "for reference", and the
dev Compose stack mounted it.

**Problem**: On msi, the pem held a different key from SOPS in every env. Two
writers caused it. `toolkit secrets jwks` wrote SOPS and the pem once, and
nothing kept them in step afterwards. `toolkit credentials generate` minted a
new key on every run and wrote it only to the pem. The generator also read the
pem into a template variable that no template used, so its "JWKS PEM not found"
warning pointed at a file nothing needed. Each copy looked authoritative to
whoever read it.

**Solution**: SOPS is the only store (SEC-032). The dev stack receives the key
as a Compose secret sourced from the variable the toolkit already exports from
SOPS (`secrets: {x: {environment: VAR}}`). Compose writes that secret inside the
container, at the path the Authelia template reads, so no host file exists.
Neither writer writes a pem any more. A guard test fails if any code under
`toolkit/` or `infra/` names a host copy again.

**Rule**: Do not keep a "copy for reference" of a secret. A copy that nothing
reconciles is a second store, and it drifts the first time either side is
written. If a consumer needs a file, have the runtime create it from the one
store at start, inside the consumer, and never write it to disk.

**Tags**: `#sops` `#oidc` `#2242` `#2227`
