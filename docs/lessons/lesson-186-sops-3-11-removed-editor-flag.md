---
id: lesson-186-sops-3-11-removed-editor-flag
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# SOPS 3.11 removed --editor flag

**Context**: `make secrets ENV=prod` fails with `flag provided but not defined: -editor`.

**Problem**: SOPS 3.11 changed the editor flag. The `--editor` CLI flag was removed in favor of `SOPS_EDITOR` or `EDITOR` environment variables.

**Solution**: Use `sops edit <file>` (picks up `$EDITOR`) or `EDITOR=nano sops edit <file>`. Fix the toolkit `secrets edit` command to use env var instead of `--editor` flag.

**Rule**: Pin SOPS version in toolkit or check for breaking changes on upgrade. The `sops unset` command works for removing keys without opening an editor.
