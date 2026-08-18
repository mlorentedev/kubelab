---
id: lesson-103-yamllint-directives-don-t-work-inside-yaml-li
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# yamllint Directives Don't Work Inside YAML Literal Block Scalars

**Context**: Pre-commit yamllint failed on argon2 hash lines (126 chars > 120 max) inside Authelia's `configuration.yml: |` block in K8s ConfigMaps.

**Problem**: Added `# yamllint disable rule:line-length` / `# yamllint enable rule:line-length` comments inside the `|` block. yamllint still reported errors. Root cause: inside a YAML literal block scalar (`|`), everything is string content — `#` comments are part of the string, not YAML comments. yamllint can't parse directives embedded in string content.

**Solution**: Bumped yamllint `line-length.max` from 120 to 130 in `.pre-commit-config.yaml`. This accommodates standard argon2 hash output (typically ~126 chars) without disabling line-length checking entirely.

**Rule**: yamllint inline directives (`# yamllint disable/enable`) only work in actual YAML comment positions, not inside literal block scalars (`|`), folded scalars (`>`), or quoted strings. For long lines inside `|` blocks, adjust the global `line-length.max` config.
