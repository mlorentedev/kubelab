---
id: "SEC-032-oidc-key-from-sops"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-14"
issue: "mlorentedev/kubelab#2242"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "TF-007 archives with #2239; the other over-limit specs belong to other lanes, whose abandonment is the operator's call (flagged in the 2026-10-14 handoff) (17 active, limit 10, 2026-10-14)"
---

# SEC-032-oidc-key-from-sops

> **Naming**: file lives at `<repo>/specs/SEC-032-oidc-key-from-sops/proposal.md`. `SEC-032-oidc-key-from-sops` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #2242: SEC-032: the OIDC signing key has a disk copy that drifts from SOPS -->

The OIDC signing key has two stores: SOPS (`apps.services.security.authelia.oidc_jwks_private_key`), which K8s Authelia serves in both envs (verified live 2026-10-13), and a gitignored `infra/config/secrets/{env}.oidc-jwks.pem` written by `toolkit secrets jwks` and synced by nothing. On msi every pem holds a different key from SOPS, and the files live on one workstation with mode 664 (SEC-030 #2227). A second store that nothing reconciles is a drift waiting to be served.

## What

SOPS is the only store, and no command writes the key to the host disk.

- The dev Compose stack receives the key as a Compose secret sourced from the `APPS_SERVICES_SECURITY_AUTHELIA_OIDC_JWKS_PRIVATE_KEY` variable that the toolkit already exports from SOPS. The secret is mounted at the same in-container path the template reads (`/config/secrets/oidc-jwks.pem`), so the Authelia template does not change, and no host file exists.
- `generate_jwks` stops writing the pem. `credentials generate` stops minting a key at all: it created a new one on every run and wrote it only to the pem, which is how each pem drifted from SOPS. Rotating stays the explicit `toolkit secrets jwks`. `generator_authelia` stops reading it: its value went into a template variable that no template uses, so the read was dead code that only logged a misleading warning.
- `JWKS_FILE_TEMPLATE` goes. The runbooks that call the pem "committed" or list it as a store are fixed.

## Out of scope

- Deleting the msi copies. msi stays untouched until the operator retires it. The handoff names the three files as safe to delete once this lands.
- Rotating any key. SOPS already holds what prod and staging serve.
- K8s, which already reads SOPS through `authelia-secrets`.

## Risks / open questions

- Compose's environment-sourced secret needs Compose v2.23 or later. Measured on the Mac, Compose 5.6.0 with Colima: a multi-line value arrives intact at an absolute `target`, mode 0444, and there is no host file.
- Authelia's `secret` template function strips no newlines. The value arrives exactly as SOPS holds it, just as it did from the pem.
- Decisions taken autonomously per the operator's instruction of 2026-10-14 (advisor consulted). The operator can overrule them on review.

## Acceptance criteria

- [ ] AC1: the dev Compose stack mounts no `*.oidc-jwks.pem` from the host. It declares the key as a secret sourced from `APPS_SERVICES_SECURITY_AUTHELIA_OIDC_JWKS_PRIVATE_KEY` and targeted at the path the Authelia template reads. A test ties the two paths together.
- [ ] AC2: `toolkit secrets jwks` stores the key in SOPS and writes no file; `credentials generate` neither mints nor writes one. A test runs `generate_jwks` against a temporary project root and finds no file, and the AC3 guard covers both writers.
- [ ] AC3: nothing in `toolkit/` or `infra/` reads or writes a host `oidc-jwks.pem`. A guard test fails if one reappears.
- [ ] AC4: with no pem on disk, dev Authelia loads the SOPS key. Verified live: `authelia validate-config` passes in the dev stack on the Mac, and the public key of the mounted key matches SOPS's. Fingerprints are compared, never the key.
- [ ] AC5: `docs/runbooks/sops-and-secrets.md` and `docs/runbooks/secrets-reference.md` name SOPS as the only store, and a lesson records the drift.

## References

- Issues: #2242 (this), #2227 SEC-030 (closes, except deleting the msi copies), epic TF-014 #2225 (C17: nothing machine-local)
- Compose spec, `secrets.environment`; Authelia `configuration/methods/secrets` (file over environment)
