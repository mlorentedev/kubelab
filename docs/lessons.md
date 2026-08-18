---
id: kubelab-lessons
type: lesson
status: active
created: "2026-05-10"
owner: manu
tags: [kubelab, lessons, pointer]
---

# Lessons Learned

> **Moved.** This file was a 4,300-line monolith. Lessons are now one file each
> under [`docs/lessons/`](lessons/_index.md), grouped by category, so a session
> can load the index without loading the corpus.
>
> **Writing a new lesson? Do NOT append here.** Create
> `docs/lessons/<category>/lesson-NNN-<slug>.md` at the next free number and add
> its row to that category's `_index.md`. The format is in
> [`docs/lessons/_format.md`](lessons/_format.md). Appending to this file
> recreates the monolith on top of the pointer.

**[Browse all lessons](lessons/_index.md)**

This stub stays so existing citations keep resolving — several test files and
manifests cite `docs/lessons.md` with a date (for example
`tests/infra/test_k3s.py:223`). To find a cited lesson, grep the tree:

```bash
grep -rl "2026-08-09" docs/lessons/
```
