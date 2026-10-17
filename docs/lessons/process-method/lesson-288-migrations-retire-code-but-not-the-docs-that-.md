---
id: lesson-288-migrations-retire-code-but-not-the-docs-that-
type: lesson
status: active
created: "2026-07-07"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Migrations retire code but not the docs that described the old world (docs audit)

**Context:** Full documentation audit (`docs/audits/docs-audit-2026-07-07.md`, 92 findings D1-D92). The platform went through three migrations (Proxmox→bare-metal, Compose→K3s+GitOps, Gitflow→trunk+release-please) and the code plus the *newest* docs are correct.

**Problem:** Every migration left the previous generation of docs alive and unmarked: README still described Compose prod and swapped node roles; `docs/architecture/diagram.md` drew an architecture two migrations old; `cicd.md`/`deployment.md`/`toolkit.md` taught a pipeline and CLI that no longer exist; troubleshooting kept fictional services (Portainer, Vaultwarden). The docs a newcomer reads FIRST were the most wrong, while niche recent runbooks were accurate — drift concentrates in the outer ring because nobody re-reads it after landing the migration.

**Solution:** Audit report with stable finding IDs + 4 remediation tickets (#824-#827). #824 (entry-surfaces sweep) executed: truth fixes in README/CONTRIBUTING/CLAUDE.md, retirement stubs pointing at the canonical successors, `superseded`/`historical` banners on dead runbooks.

**Rule:** A migration's definition of done must include retiring or banner-marking the docs that described the old world — same PR or a named follow-up ticket, never "later". Docs that restate SSOT data (node roles, IPs, service lists, command tables) drift by construction: reference `common.yaml`/the CLI instead of copying, or generate the table. When retiring a doc, replace it with a stub that redirects to the canonical successor so inbound links keep working.

**Tags:** `#docs` `#drift` `#ssot` `#audit` `#migrations`
