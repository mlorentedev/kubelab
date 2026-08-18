---
id: lesson-061-operational-notes-go-in-runbooks-not-the-road
type: lesson
status: active
created: "2026-02-21"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Operational Notes Go in Runbooks, Not the Roadmap (repeated error 2x)

**Context**: When marking MON-002 and HW-019 as completed, I added operational notes (flags, root cause, fix) directly in roadmap.md. Both times I had to be corrected.

**Problem**: The roadmap is for tasks (state, progress). Operational notes (flags, config, troubleshooting, root causes) belong in the corresponding runbook. The urge to annotate context next to the `[x]` is strong but wrong.

**Solution**: Remove the note from the roadmap. Document in the runbook (40-runbooks/hardware-setup.md, headscale-setup.md, etc.).

**Rule**: **BEFORE adding any note to roadmap.md, ask: "Is this WHAT TO DO or HOW TO DO IT?"** If "how" → it goes in the runbook. The roadmap only has: task ID, title, status, date. Nothing else.

---
