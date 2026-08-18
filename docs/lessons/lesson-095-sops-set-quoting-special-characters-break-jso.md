---
id: lesson-095-sops-set-quoting-special-characters-break-jso
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# sops --set Quoting: Special Characters Break JSON Parsing

**Context**: Automating SOPS secret injection via Makefile targets.

**Problem**: `sops --set '["path"] "value!"'` fails with "Value for --set is not valid JSON" when the value contains `!` (bash history expansion) or other special characters.

**Solution**: Avoid special characters in passwords passed via `sops --set`. For passwords with special chars, use `sops --edit` (interactive) or pipe through environment variables with proper escaping. Created `make secrets ENV=staging` for interactive editing and `make secrets-init` for automated generation of random hex secrets (no special chars).

**Rule**: `sops --set` values must be valid JSON. Use hex-encoded random values for automated injection. Reserve interactive `sops --edit` for human-chosen passwords with special characters.

---
