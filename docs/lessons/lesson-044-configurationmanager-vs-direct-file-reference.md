---
id: lesson-044-configurationmanager-vs-direct-file-reference
type: lesson
status: active
created: "2026-02-05"
owner: manu
tags: [kubelab, lesson]
---

# ConfigurationManager vs Direct File References

**Context**: Discovering why some toolkit operations would work and others wouldn't.

**Problem**: `configuration.py:144-168` has the correct logic (compose.base.yml + compose.{env}.yml with legacy fallback), but 4 CLI modules build filenames directly without using ConfigurationManager.

**Solution**: Identify and migrate all modules to use ConfigurationManager.get_compose_files().

**Rule**: Single source of truth for file resolution. Never build compose paths in more than one place. If an abstraction exists, use it.
