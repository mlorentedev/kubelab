---
id: lesson-128-pre-flight-ssh-validation-prevents-ssh-harden
type: lesson
status: active
created: "2026-03-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Pre-flight SSH validation prevents ssh_hardening lockout

**Context:** ADR-023 Phase 1 provisioning review — ssh_hardening role disables password auth
**Problem:** The ssh_hardening role disables password authentication and enables key-only auth. If the SSH key isn't already authorized on the target, the operator gets locked out with no recovery path. On fresh Ubuntu 24.04 installs, this is a real risk.
**Solution:** Add a pre-flight play (Play 0) at the start of provisioning playbooks. No become, no gather_facts. Three checks: (1) ansible.builtin.ping — verifies SSH+Python, (2) sudo -n true — verifies become works, (3) stat on SSH key file — verifies key exists on controller. If any fails, playbook stops before touching anything. Standard professional practice for hardening playbooks.
**Tags:** `#ansible` `#ssh` `#security` `#provisioning`
