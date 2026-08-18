---
id: lesson-192-ai-knowledge-persistence-vault-is-the-record-
type: lesson
status: active
created: "2026-03-25"
owner: manu
tags: [kubelab, lesson]
---

# AI knowledge persistence: vault is the record, MEMORY.md is cache

**Context**: During a long session with multiple fixes (IMMUTABLE_SECRETS, CrowdSec, Gitea, trusted_cidrs), detected 6 debt items and 5 lessons. Initially only wrote to MEMORY.md, not to the vault.

**Problem**: MEMORY.md is ephemeral — it gets truncated, compressed, or lost between machines. Tasks, lessons, and decisions written only to MEMORY.md are effectively lost. The vault (`~/Projects/knowledge/`) is synced via Obsidian and is the only durable record.

**Solution**: Write to vault immediately when detecting a task (`11-tasks.md`), lesson (`90-lessons.md`), or decision (`14-changelog.md`). Don't batch at session end. Treat MEMORY.md as index/cache only.

**Rule**: Every annotation = vault + MEMORY.md. Never just MEMORY.md. If it's not in the vault, it didn't happen. See also: `00_meta/patterns/pattern-decision-persistence.md`.

---
