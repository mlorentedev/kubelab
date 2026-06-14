---
tags: [spec, tasks]
created: "2026-06-14"
---

# Tasks - WEB-010-interactive-cv

> One task = one focused commit/PR. Maps to epic kubelab#611 child issues. Reorder freely while spec is in `draft`.

## Setup

- [ ] Work in kubelab worktree (foreign-repo rule); branch `feat/mlorente-dev-interactive-cv`
- [ ] `proposal.md` acceptance criteria reviewed (remove the `[AGENT-DRAFT]` tag)
- [ ] Open questions resolved — esp. IDP-023 (#299) pgvector blocker

## Stream A — Brand & funnel (no infra; start now)

- [ ] WEB-011 (#602) Reposition `site.ts`/Hero + clean design pass
- [ ] WEB-012 (#603) CV-as-landing: experience timeline + quantified credibility band
- [ ] WEB-013 (#604) Email funnel (primary) + ambiguous "work with me" CTA
- [ ] WEB-014 (#605) Case-study template + author two (hive, homelab)

## Stream B — Knowledge plane (backend RAG)

- [ ] IDP-023 (#299) Postgres + pgvector on prod K3s **[BLOCKER]**
- [ ] IDP-027 (#395) embedding pipeline (honours `rag:public` allowlist)
- [ ] IDP-028 (#396) `/v1/knowledge/search`
- [ ] WEB-015 (#606) corpus governance (`rag:public` allowlist + exclusions)
- [ ] WEB-016 (#607) `POST /v1/knowledge/chat` endpoint

## Stream C — Chatbot frontend

- [ ] WEB-017 (#608) chat island wired → **MVP bot live**
- [ ] WEB-018 (#609) boundaries v1 (keyword + canary + refusal)

## Stream D — Proof surfaces

- [ ] WEB-019 (#610) PS2 GitHub/OSS telemetry (MVP)
- [ ] PS1 homelab `/ops` (Release 2)
- [ ] PS3 knowledge garden (Release 2; renders the curated corpus)

## Closing

- [ ] Every acceptance criterion covered by a test/smoke check
- [ ] `features.json` emitted (one feature per acceptance criterion)
- [ ] `verification.md` filled
- [ ] PR opened referencing this spec folder

## Machine-readable features

Emit a sibling `features.json` (one feature per acceptance criterion: `id`, `behavior`, `verification`, `state`, `evidence`). The agent CANNOT set `state: passing` — only the harness, after running `verification` with exit 0, may.
