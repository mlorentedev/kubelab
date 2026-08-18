---
id: lesson-345-vault-awaiting-architecture-session-framing-c
type: lesson
status: active
created: "2026-08-10"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Vault "awaiting architecture session" framing can be stale — check for a closed ticket/merged ADR before trusting it

**Context:** Session split into two lanes (2026-08-10 fronts-inventory-and-lane-split.md); lane B picked up F4 (Strands Agents) and F5 (ADR-043 memory plane), both framed by the vault note and the user's own recollection as open/pending decisions.
**Problem:** Both fronts turned out to be based on stale premises, in the same session: F4's "zero prior assessment" ignored a real audited evaluation that existed in a sibling project's vault folder (only a repo-scoped grep was run). F5's "awaiting an architecture session to ratify or amend" was flatly wrong — the session had already happened two months earlier: ADR-043 was `status: accepted`, merged to master 2026-06-12, and its architecture-session ticket (AI-006 #595) was closed. The vault research doc that fed it never got its header updated after the ADR merged, so it kept reading as a live recommendation.
**Solution:** Before treating any vault note's "pending decision" / "awaiting ratification" framing as current: (1) search the vault as a whole, not just the current project, for prior audited work on the same topic; (2) check the repo's docs/adr/ for an ADR that already cites the research doc or the same ticket number, and check whether that ADR's status is accepted/merged rather than assuming the cited ticket is still open. `git log --diff-filter=A` on the ADR file plus `gh issue view` on the cited ticket resolves this in under a minute and is cheap insurance against re-running a session that already happened.
**Tags:** `#vault-hygiene` `#architecture-session` `#verification` `#regla-del-3`
