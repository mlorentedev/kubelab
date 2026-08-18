---
id: lesson-028-toolkit-kubeconfig-path-must-be-env-parameter
type: lesson
status: active
created: "2026-03-19"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# Toolkit kubeconfig path must be env-parameterized

**Context**: Running `toolkit infra k8s deploy --env staging` after Ansible generates per-env kubeconfigs at `~/.kube/kubelab-{env}-config`.

**Problem**: `_get_kubeconfig()` in `toolkit/cli/infra.py` used a hardcoded path `~/.kube/kubelab-config` (no env suffix). Ansible generates `kubelab-staging-config`, `kubelab-prod-config`, etc. The toolkit could never find the right kubeconfig for any env unless `KUBECONFIG` env var was set manually.

**Solution**: Replaced hardcoded `_K8S_DEFAULT_KUBECONFIG` with `_K8S_KUBECONFIG_PATTERN = "~/.kube/kubelab-{env}-config"`. `_get_kubeconfig()` now requires an `env` argument. `KUBECONFIG` env var still takes precedence.

**Rule**: Any path that varies by environment must be parameterized with `{env}`, not hardcoded. When Ansible generates env-specific outputs, the toolkit must use the same naming convention. Check path alignment whenever adding a new env-aware resource.
