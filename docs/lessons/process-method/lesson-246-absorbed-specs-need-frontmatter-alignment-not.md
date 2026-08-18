---
id: lesson-246-absorbed-specs-need-frontmatter-alignment-not
type: lesson
status: active
created: "2026-05-10"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Absorbed specs need frontmatter alignment, not just body warnings

**Context:** During vault audit (2026-05-10), `kubelab/30-architecture/components/kubelab-gateway.md` and `kubelab-memory.md` were both found with `status: active` in YAML frontmatter while the body opened with `> Status: absorbed — Do not implement`. Both were rewritten on 2026-05-09 after being absorbed into ADR-029 on 2026-03-28.
**Problem:** When a spec is absorbed into another doc (e.g. ADR), keeping the file as historical reference is fine — but if frontmatter `status` stays `active`, the SSOT-detection tooling, validators, link-graph queries, and any agent reading metadata will treat it as live work. The body warning ("Do not implement") is invisible to programmatic readers. This produces silent drift: humans see "absorbed", machines see "active". A reader could mistakenly resurrect the spec or build dependencies against it.
**Solution:** When absorbing a spec, atomically update three things in the same commit: (1) frontmatter `status: absorbed` (or `archived`), (2) add `absorbed_by: <target-id>` and `absorbed_on: YYYY-MM-DD` fields so the dependency graph captures the link, (3) keep the body warning AND ensure `_ssot.md` reflects the absorption in its "Absorbed Specs" section. The vault `types.json` schema should include `absorbed_by` and `absorbed_on` as standard fields when this pattern recurs. Applied today: gateway.md and memory.md frontmatter corrected with `status: absorbed` + `absorbed_by` + `absorbed_on`.
**Tags:** `#vault-health` `#ssot` `#frontmatter` `#drift` `#adr`
