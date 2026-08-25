---
id: lesson-379-rotating-a-username-is-not-rotation-it-is-a-rename
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets, gitea, credentials, rotation, ssot, adr-062, auth-004]
---

# Rotating a username is not rotation, it is a rename — and an identity resolved from a secret store is one something else is entitled to change

**Context**: The 2026-08-20 credential exposure was being closed out. `make credentials-generate ENV=prod` rotated the prod set, which includes `basic_auth.user` — the Traefik dashboard's basic-auth username. Prod Gitea SSO went down and stayed down, answering `invalid_client`, and the next provision run did not repair it. Narrative: `sessions/2026-08-23-kubelab-claude-auth004-sso-incident.md`; tickets #1355, fix #1352.

**Problem**: `provision-bee.yml` resolved Gitea's admin username from `gitea_secrets.basic_auth.user` — a Traefik credential aliased into application identity with no semantic relationship to it. Two consequences compounded:

1. The alias made Gitea's admin *username* a secret, and therefore a value `credentials-generate` was entitled to rotate. Rotating it did not re-credential the admin; it **redefined which account was the admin**.
2. `gitea-bootstrap.sh` is idempotent on username (`gitea admin user list | awk 'NR>1 {print $2}'`), so under the new name it took the `create` branch, tried to create a *second* admin, and collided on the shared contact e-mail. The script aborted at `create` — which sits **before** its own `gitea admin auth update-oauth`. The rotated OIDC client secret was never delivered.

The failure shape is what makes this expensive: the same run that broke SSO also destroyed the path that repairs SSO. Re-running provision could not converge, because it died at the same `create` every time.

**Solution**: #1352 resolved `gitea_admin_user` from `gitea_config` (plaintext `common.yaml` merged with the prod values file) instead of from the secret store, under ADR-062 D3 / AUTH-004 AC1. The identity is now a plaintext SSOT key that `credentials-generate` has no reach into. The inline comment at `infra/ansible/playbooks/provision-bee.yml:224` and the receipt at `infra/config/values/common.yaml:619` both record why the distinction is load-bearing.

**Rule**: An identity is not a credential, and the two must not share a storage location. Ask of every value a playbook reads from SOPS: *if a rotation command changed this, would the service get a new password, or a new principal?* If the answer is "a new principal", it belongs in plaintext SSOT — `common.yaml` — not in the secret store, no matter how convenient the alias. Corollary for bootstrap scripts: an idempotence check keyed on the identity (`does user X exist?`) silently converts a rename into a create, so order the script's steps so that credential delivery does not sit behind account creation. A repair path that runs after the thing it repairs has broken it is not a repair path.

**Tags**: `#gitea` `#rotation` `#ssot` `#identity` `#adr-062` `#auth-004` `#pr-1352`
