---
id: lesson-182-k8s-1-24-serviceaccount-tokens-require-explic
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# K8s 1.24+ ServiceAccount tokens require explicit Secret

**Context**: Creating long-lived SA token for Argo CD spoke authentication.

**Problem**: K8s 1.24+ stopped auto-generating persistent SA tokens. Creating a ServiceAccount no longer creates a companion Secret with a token. Without the explicit Secret, there's no token to extract for hub registration.

**Solution**: Create a Secret of type `kubernetes.io/service-account-token` with annotation `kubernetes.io/service-account.name: <sa-name>`. K8s token controller detects this and populates `.data.token` and `.data.ca.crt`. The token is long-lived (doesn't expire) — suitable for service-to-service auth but requires manual rotation if compromised.

**Rule**: For K8s 1.24+, always create explicit token Secrets for ServiceAccounts that need persistent tokens. Never rely on auto-generation. Include a rotation mechanism (Makefile target or CronJob).
