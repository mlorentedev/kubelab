---
id: "WEB-010-interactive-cv"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-06-14"
issue: "kubelab#611"
tags: [spec, proposal]
template_version: "1.0"
---

# WEB-010: mlorente.dev interactive-CV migration

> **Naming**: `kubelab/specs/WEB-010-interactive-cv/`. Epic: kubelab#611. Anchored by ADR-045.
> `[AGENT-DRAFT — review before archive]` — the sections below were pre-drafted from ADR-045; refine via `/spec fill` and remove this tag before archive.

## Why

<!-- from issue #611: WEB-010: mlorente.dev to interactive CV (RAG chat + living-telemetry proof surfaces) -->

`mlorente.dev` is a static, passive portfolio with stale positioning and thin conversion. To serve employability (primary) and audience-building for the upcoming YouTube channel, the site must *demonstrate* platform/AI-engineering ability rather than assert it: an interactive CV with a RAG chatbot grounded on a curated vault corpus, plus read-only "proof-surface" dashboards backed by real systems Manu operates. This executes the already-decided roadmap (ADR-031/029/043) with santifer.io as a de-risking reference implementation. If we don't ship it, the site keeps under-converting and the proof-of-work stays invisible.

## What

- A public "Ask me / Pregúntame" chat island on `mlorente.dev` that answers in first person from a curated vault corpus, served by a new `POST /v1/knowledge/chat` in the Go API (agentic RAG over self-hosted pgvector, managed inference).
- A repositioned, quantified, CV-as-landing site (clean miia-style design) with an **email-capture primary CTA** + an ambiguous **"work with me"** secondary CTA (employment or consulting).
- At least one live **proof surface** (GitHub/OSS telemetry), with the homelab `/ops` and knowledge garden as fast-followers.

## Out of scope

- Voice mode, evals-as-CI-gate, and the self-healing loop (backlog; santi-parity later).
- Proof surfaces PS4–PS6 (DORA, bot LLMOps, agent feed) — catalogued, not MVP.
- Any domain change (`mlorente.dev` stays; a `.io` move is a separate decision under ADR-017).

## Risks / open questions

- **[MUST resolve before code]** IDP-023 (pgvector on prod K3s, #299) is the critical-path blocker; the bot backend cannot run without it.
- Corpus leakage: the curated `rag: public` allowlist MUST exclude private strategy/employment material (fail-safe allowlist, never a denylist).
- Managed-inference provider (NaN cloud vs Claude) + a per-conversation cost guard — decide at WEB-016.
- Public proof-surface exposure review (no secret/PII leakage; read-only; rate-limited).

## Acceptance criteria

- [ ] `POST /v1/knowledge/chat` returns a streamed, first-person answer grounded in ≥1 retrieved curated-corpus chunk, with source attribution, behind a rate limit.
- [ ] The "Ask me" island is live on `mlorente.dev` (bilingual) and answers a known question about Manu's experience correctly.
- [ ] The corpus pipeline indexes ONLY `rag: public`-allowlisted docs (a private/denied doc is provably absent from retrieval).
- [ ] `mlorente.dev` hero + landing reflect the locked positioning, with a working email-capture CTA.
- [ ] One proof surface (GitHub/OSS telemetry) renders live on the site.

## References

- ADR: `kubelab/docs/adr/adr-045-mlorente-dev-interactive-cv.md` (+ ADR-031 / ADR-029 / ADR-043 / ADR-042)
- Epic + tasks: kubelab#611 (WEB-010) → #602–#610 (WEB-011..019); IDP-023 #299 / IDP-027 #395 / IDP-028 #396
- Vault: `10_projects/kubelab/20-business/strategy/interactive-cv-reference-analysis-2026-06-13.md`
