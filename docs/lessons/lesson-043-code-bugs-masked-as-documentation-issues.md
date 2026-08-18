---
id: lesson-043-code-bugs-masked-as-documentation-issues
type: lesson
status: active
created: "2026-02-05"
owner: manu
tags: [kubelab, lesson]
---

# Code Bugs Masked as Documentation Issues

**Context**: Full project audit before Sprint 0.

**Problem**: The previous plan treated everything as "align documentation" but there were real code bugs:
- Toolkit references `docker-compose.{env}.yml` in 6 files, but actual files are `compose.{base|dev|staging|prod}.yml`
- `toolkit edge` imported but never registered in CLI
- `toolkit apps` removed but documented as active
- `pre-push.sh` runs `task lint` without an existing Taskfile

**Solution**: Split Sprint 0 into 0A (fix code) → 0B (align docs) → 0C (validate+commit).

**Rule**: Always audit executable code before touching documentation. A `grep -rn` of critical patterns is worth more than 14 documentation tasks.
