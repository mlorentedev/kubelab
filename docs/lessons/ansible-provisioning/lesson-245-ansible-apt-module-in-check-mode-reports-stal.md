---
id: lesson-245-ansible-apt-module-in-check-mode-reports-stal
type: lesson
status: active
created: "2026-05-10"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Ansible apt module in --check mode reports stale-cache false positives

**Context:** Running `toolkit infra ansible run -p provision-aws1 -e hub --check` against aws1 during RELIAB-009 §9.0 pre-deploy validation. Goal: confirm idempotent convergence before applying to live K3s hub. The playbook had passed yamllint and `ansible-playbook --syntax-check` cleanly.
**Problem:** Dry-run failed on `base_system : Install base packages` with `No package matching 'unzip' is available`, despite unzip being a standard Ubuntu 24.04 package. The preceding `apt: update_cache: true` task reported `changed=true` but the package lookup still failed. The host was a freshly-cloud-init-bootstrapped t4g.small with whatever apt cache cloud-init left behind weeks ago.
**Solution:** In `--check` mode the `apt` module's `update_cache: true` is a no-op — it returns `changed=true` for reporting but does NOT execute `apt-get update`. Subsequent `apt: name=<pkg>` tasks then resolve names against whatever stale cache exists on the target, often missing packages added since the cache was last refreshed. Operational rule: treat --check failures inside `apt: name=...` tasks as artifacts of check-mode semantics, not real regressions. Validate the rest of the playbook in --check (pre-flight asserts, file templates, handlers), then run for real (without --check) to confirm package installation. Do NOT add `check_mode: no` to apt tasks — that defeats the purpose of dry-runs on the rest of the role. Optional improvement: run `apt-get update` via SSH against the target as a manual pre-step when --check coverage of the full role is needed (one-shot, doesn't pollute the playbook).
**Tags:** `#ansible` `#apt` `#check-mode` `#dry-run` `#gotcha` `#cloud-init`
