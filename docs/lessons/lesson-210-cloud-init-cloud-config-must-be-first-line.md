---
id: lesson-210-cloud-init-cloud-config-must-be-first-line
type: lesson
status: active
created: "2026-03-26"
owner: manu
tags: [kubelab, lesson]
---

# cloud-init `#cloud-config` must be first line

**Context**: Recreating aws1 Spot instance via Terraform.

**Problem**: cloud-init.yml had `# yamllint disable-line rule:comments` before `#cloud-config`. Cloud-init requires `#cloud-config` as the absolute first line to identify the file format. With the yamllint comment first, cloud-init treated the entire file as unknown format and skipped all configuration (users, packages, runcmd, swap — everything).

**Solution**: Move `#cloud-config` to line 1. Use `# yamllint disable-file` as line 2 instead (disables all yamllint rules for the file, avoids per-line directives).

**Rule**: `#cloud-config` must ALWAYS be the first line. No comments, no whitespace, no BOM before it. yamllint directives go on line 2+.
