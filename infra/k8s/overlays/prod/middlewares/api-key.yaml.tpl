# Template for Traefik Middleware "api-key-*" (ADR-035 Stage 1).
#
# Rendered + applied by `make apply-middleware-secrets ENV=prod` via
# toolkit/features/k8s_middlewares.py. Placeholders substituted at render time:
#
#   ${NAME}       — metadata.name (e.g. api-key-ollama)
#   ${NAMESPACE}  — metadata.namespace (defaults to "kubelab")
#   ${SERVICE}    — logical service id, written to a label (e.g. ollama)
#   ${API_KEY}    — SOPS-sourced plaintext API key (rendered output IS gitignored)
#
# Plugin: github.com/dtomlinson91/traefik-api-key-middleware v0.1.2+
# Registered in: infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2
#
# Status code: this plugin returns HTTP 403 for any rejected request (missing,
# invalid, or wrong-keyed header). Same code for all failure modes — see ADR-035.
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: ${NAME}
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/managed-by: kubelab-toolkit
    app.kubernetes.io/component: auth-middleware
    kubelab.live/service: ${SERVICE}
spec:
  plugin:
    api-key:
      # Stage 1: X-API-Key header is the canonical auth path.
      authenticationHeader: true
      authenticationHeaderName: X-API-Key
      # Stage 2 forward-compat (per ADR-035): also accept Bearer tokens. When
      # kubelab-agents L1 ships with OIDC client_credentials, JWTs land in the
      # SAME Authorization: Bearer header that this Middleware already accepts,
      # so existing clients keep working through the migration window.
      bearerHeader: true
      bearerHeaderName: Authorization
      # Strip both headers before proxying to the backend (defense in depth:
      # backend access logs never see the key; backend cannot reflect it).
      removeHeadersOnSuccess: true
      keys:
        - ${API_KEY}
