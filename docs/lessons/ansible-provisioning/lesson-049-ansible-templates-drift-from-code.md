---
id: lesson-049-ansible-templates-drift-from-code
type: lesson
status: active
created: "2026-02-09"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# Ansible Templates Drift from Code

**Context**: Auditing Ansible templates after major refactoring (infra/compose → infra/stacks).

**Problem**: Templates in `infra/ansible/templates/` still reference `infra/compose`, K3s ports (6443), wiki, n8n, wireguard. Templates silently diverge when the repo is refactored without updating Ansible.

**Solution**: Audit templates every time the project structure changes. Include Ansible in the refactoring checklist.

**Rule**: Ansible templates are first-class citizens. A refactoring is not complete until Ansible templates are aligned.
