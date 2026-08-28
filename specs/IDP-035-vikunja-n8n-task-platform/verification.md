---
tags: [spec, verification, vikunja, n8n, slack]
created: "2026-08-27"
---

# Verification - IDP-035: Self-Hosted Task Platform (Vikunja + n8n + Slack)

> Record real command outputs and test executions produced during the implementation.

## 1. Unit & Static Tests

```bash
$ poetry run pytest tests/test_postgres_provisioner.py tests/test_stateful_service_classification.py tests/test_spec_gate.py -v
============================== 65 passed in 6.77s ==============================

$ poetry run ruff check toolkit/features/postgres_provisioner.py toolkit/features/k8s_secrets.py tests/test_postgres_provisioner.py
All checks passed!

$ poetry run mypy toolkit/features/postgres_provisioner.py toolkit/features/k8s_secrets.py
Success: no issues found in 2 source files
```

## 2. Kubernetes Deployment Verification (Staging / Prod)

```bash
$ kubectl kustomize infra/k8s/overlays/staging | grep -A 10 "name: vikunja"
    app.kubernetes.io/name: vikunja
    app.kubernetes.io/part-of: kubelab
  name: vikunja-config
  namespace: kubelab
...

$ kubectl kustomize infra/k8s/overlays/prod | grep -A 10 "name: vikunja"
    app.kubernetes.io/name: vikunja
    app.kubernetes.io/part-of: kubelab
  name: vikunja-config
  namespace: kubelab
...
```

## 3. Idempotent Platform Reconciler Execution

```bash
# Run 1: Bootstrap namespaces, standard labels, and webhooks
make sync-vikunja ENV=staging

# Run 2: Re-run to verify strict idempotency (changed=0)
make sync-vikunja ENV=staging
```

## 4. Multi-Forge Lifecycle Webhook Verification

```bash
# Trigger simulated PR event (GitHub and Gitea)
# Verify Vikunja task state transition (In Progress -> In Review -> Done)
```

## 5. Slack ChatOps Verification

```bash
# Execute `/task create` and verify confirmation in Slack
# Verify #dev-activity notification emission
```
