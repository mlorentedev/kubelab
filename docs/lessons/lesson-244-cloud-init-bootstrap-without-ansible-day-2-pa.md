---
id: lesson-244-cloud-init-bootstrap-without-ansible-day-2-pa
type: lesson
status: active
created: "2026-05-09"
owner: manu
tags: [kubelab, lesson, ansible, terraform, cloud-init, iac, day-2-operations, argocd, aws, drift]
---

# Cloud-init bootstrap without Ansible day-2 path is invisible technical debt

**Context:** Investigating RELIAB-009 (Argo CD hub memory hygiene fix). The vault plan said 'Apply via make provision NODE=aws1 ENV=hub' but no such command existed. aws1 was bootstrapped via Terraform cloud-init (AWS-001..005, done 2026-03-22) which set up K3s on first boot. There was never an Ansible role applied to aws1 — only Terraform creating the instance and cloud-init running once on first boot.
**Problem:** When a node is bootstrapped purely via cloud-init (Terraform user-data) and the operator assumes an Ansible day-2 path exists for it, that assumption can persist undetected for weeks. Plans get written referencing `make provision NODE=X ENV=Y` style commands that look reasonable because they exist for other nodes — but the playbook (`provision-aws1.yml`), inventory group placement (`k3s_servers`), env config file (`hub.yaml`), and Makefile dispatcher case may all be missing. The gap only surfaces when a config drift fix needs to land (here: K3s `--kube-controller-manager-arg=terminated-pod-gc-threshold=100`). Risk: emergency fixes get applied via SSH/manual edits, creating drift between IaC and reality.
**Solution:** Two complementary rules: (1) Every node bootstrapped by cloud-init MUST also have an Ansible day-2 playbook before the bootstrap is considered complete. Even if the playbook is a thin wrapper that only invokes idempotent roles for config drift, it must exist. Acceptance criteria: `make provision NODE=<name> ENV=<env>` works on a freshly-bootstrapped node and reports 'ok' (no changes) on subsequent runs. (2) When writing remediation plans that reference automation, verify the automation exists before committing the plan to the vault. A plan that says 'apply via X' where X is hypothetical creates downstream churn — the next person reading the plan will discover the gap mid-execution. Pattern for new cloud-bootstrapped nodes (following AWS-001..005 + missing-now-RELIAB-009-9.0): Terraform cloud-init = bootstrap-only (install K3s, Tailscale, swap); Ansible playbook `provision-<node>.yml` = day-2 config (idempotent role invocation); env config `infra/config/values/<env>.yaml` = SSOT for that node's overrides; inventory group placement (`k3s_servers`, etc.) consistent with role expectations; Makefile dispatcher case for `make provision NODE=<node> ENV=<env>`. Validation: provision a node, then re-run the playbook → must report 0 changes.
**Tags:** `#ansible` `#terraform` `#cloud-init` `#iac` `#day-2-operations` `#argocd` `#aws` `#drift`
