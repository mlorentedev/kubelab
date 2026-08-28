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
$ poetry run pytest tests/test_vikunja_client.py tests/test_vikunja_reconciler.py -v
tests/test_vikunja_client.py::test_headers_include_bearer_token PASSED   [ 10%]
tests/test_vikunja_client.py::test_get_namespaces_returns_list PASSED    [ 20%]
tests/test_vikunja_client.py::test_create_namespace_success PASSED       [ 30%]
tests/test_vikunja_client.py::test_get_labels_returns_list PASSED        [ 40%]
tests/test_vikunja_client.py::test_create_label_success PASSED           [ 50%]
tests/test_vikunja_client.py::test_patch_task_uses_granular_update PASSED [ 60%]
tests/test_vikunja_client.py::test_add_task_comment PASSED               [ 70%]
tests/test_vikunja_client.py::test_api_error_raises_vikunja_error PASSED [ 80%]
tests/test_vikunja_reconciler.py::test_reconciler_creates_missing_namespaces_and_labels PASSED [ 90%]
tests/test_vikunja_reconciler.py::test_reconciler_is_strictly_idempotent_when_resources_exist PASSED [100%]
============================== 10 passed in 5.41s ==============================
```

## 4. Multi-Forge Lifecycle Webhook Verification

```bash
$ poetry run pytest tests/test_n8n_multi_forge_sync.py -v
tests/test_n8n_multi_forge_sync.py::test_hmac_verification_valid_signature PASSED [ 20%]
tests/test_n8n_multi_forge_sync.py::test_hmac_verification_invalid_signature PASSED [ 40%]
tests/test_n8n_multi_forge_sync.py::test_extract_task_key_from_branch_and_title PASSED [ 60%]
tests/test_n8n_multi_forge_sync.py::test_monotonic_state_transition PASSED [ 80%]
tests/test_n8n_multi_forge_sync.py::test_multi_forge_workflow_json_exists_and_is_valid_n8n PASSED [100%]
============================== 5 passed in 4.48s ===============================
```

## 5. Slack ChatOps & Agent Dispatcher Verification

```bash
$ poetry run pytest tests/test_n8n_slack_capture.py tests/test_n8n_agent_dispatcher.py -v
tests/test_n8n_slack_capture.py::test_slack_signature_valid PASSED       [ 12%]
tests/test_n8n_slack_capture.py::test_slack_signature_expired_timestamp_fails PASSED [ 25%]
tests/test_n8n_slack_capture.py::test_parse_slack_slash_command_create_with_project_and_priority PASSED [ 37%]
tests/test_n8n_slack_capture.py::test_parse_slack_slash_command_defaults PASSED [ 50%]
tests/test_n8n_slack_capture.py::test_slack_task_capture_workflow_json_exists_and_is_valid PASSED [ 62%]
tests/test_n8n_agent_dispatcher.py::test_agent_payload_extraction_with_delegable_label PASSED [ 75%]
tests/test_n8n_agent_dispatcher.py::test_agent_payload_ignored_without_label PASSED [ 87%]
tests/test_n8n_agent_dispatcher.py::test_agent_dispatcher_workflow_json_exists_and_is_valid PASSED [100%]
============================== 8 passed in 5.12s ===============================
```
