---
id: lesson-092-oidc-client-secret-authelia-config-vs-service
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# OIDC Client Secret: Authelia Config vs Service Config

**Context**: Deploying MinIO with Authelia OIDC on K3s staging.

**Problem**: Authelia needs the client_secret as a hash (argon2id) in its configuration.yml, while MinIO needs the plaintext secret in its MINIO_IDENTITY_OPENID_CLIENT_SECRET env var. Storing both in SOPS with different keys, or using env var injection, creates complexity.

**Solution**: Store the plaintext in SOPS at the service path (`apps.services.data.minio.oidc_client_secret`) and the hash at the Authelia path (`apps.services.security.authelia.oidc_client_secret_minio_hash`). The hash goes directly in the ConfigMap (it's irreversible, not sensitive). The plaintext goes in a K8s Secret via k8s_secrets.py. Use `make secrets-hash-minio` to generate the hash from the plaintext.

**Rule**: For OIDC client secrets, always store plaintext + hash separately in SOPS. The hash in the Authelia ConfigMap is acceptable (irreversible). Never put plaintext secrets in ConfigMaps. Use Makefile targets to automate hash generation.

---
