---
id: lesson-050-os-choice-matters-for-staging
type: lesson
status: active
created: "2026-02-09"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# OS Choice Matters for Staging

**Context**: Choosing the OS for the staging node in the homelab.

**Problem**: If staging runs Arch Linux (rolling release) and prod runs Ubuntu Server (LTS), there's an entire class of "works in staging, fails in prod" bugs caused by kernel, libc, and package differences.

**Solution**: Staging OS == Prod OS. Both Ubuntu Server 24.04 LTS.

**Rule**: Staging must be identical to prod in OS, version, and base configuration. OS differences are bugs waiting to manifest.
