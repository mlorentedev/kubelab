---
id: adr-045-mlorente-dev-interactive-cv
type: adr
status: accepted
created: "2026-06-14"
owner: manu
tags: [architecture, mlorente-dev, web, portfolio, rag, chatbot, llmops, personal-brand, astro, proof-of-work]
depends_on: [adr-031-positioning-pivot, adr-029-intelligence-layer, adr-043-unified-knowledge-memory-plane, adr-042-reference-architecture]
---

# ADR-045: mlorente.dev → Interactive-CV (RAG chat + living-telemetry proof surfaces)

> **Status:** Accepted
> **Date:** 2026-06-14
> **Related:** ADR-031 (positioning pivot — the "Chat with Manu" widget is a portfolio deliverable), ADR-029 (intelligence layer — `POST /v1/knowledge/chat`), ADR-043 (unified knowledge plane — vault → pgvector → `/v1/knowledge/search`), ADR-042 (reference architecture — always-on vs on-demand inference).
> **Reference analysis:** vault `10_projects/kubelab/20-business/strategy/interactive-cv-reference-analysis-2026-06-13.md` (santifer.io + miia.dev, incl. the MIT `cv-santiago` repo) and `positioning-authority-references-2026-06-12.md` (14 reference profiles).
> **Epic:** WEB-010.

## Context

`mlorente.dev` today is a static Astro portfolio (`output: 'static'`, served by nginx on prod VPS K3s behind Traefik + Let's Encrypt), with ~16 bilingual notes and a `portfolio.ts` project grid. It is mature on the build/deploy side but **passive** (no interactivity, thin conversion) and **stale on positioning** (`site.ts` still reads "Engineer from Silicon to Cloud").

A reference site — [santifer.io](https://santifer.io) — crystallised a model worth adopting: **the site IS the portfolio**. It is a production AI system (a first-person RAG chatbot avatar + an LLMOps dashboard + case studies) that *demonstrates* the skills it claims rather than asserting them. Its frontend bot is open source (MIT, `github.com/santifer/cv-santiago`), making it a usable reference implementation.

Critically, the backend for this is **already designed in our own roadmap**: ADR-031 makes the "Chat with Manu" widget a portfolio deliverable; ADR-029 §6 defines `POST /v1/knowledge/chat`; ADR-043 defines the knowledge plane (`vault git → chunk → embed → pgvector → POST /v1/knowledge/search`) and names a *"future public widget"* as an explicit consumer; the board already carries IDP-023 (#299) → IDP-027 (#395) → IDP-028 (#396). This ADR records the **product/site-level decision** that ties those threads together and adds two dimensions the infra ADRs do not cover: the **conversion funnel** and a **belt of "proof-surface" dashboards**.

Goal refinement from the working session: the site's **#1 job is email capture** (own the audience; feed the planned YouTube channel + newsletter); **#2 is "work with me"** — a deliberately ambiguous CTA covering both employment and consulting. The bot and proof surfaces are the trust engine that feeds both.

## Reference audit (Regla del 3)

| Dimension | R1 · santifer.io (engine) | R2 · miia.dev (chassis) | R3 · own roadmap (ADR-029/043) |
|---|---|---|---|
| Model | "the system IS the portfolio" — RAG avatar + LLMOps + case studies | Consultant minimalism: quantified credibility, availability widget, no interactivity | Knowledge plane consumed by a public widget |
| RAG backend | Supabase pgvector + BM25, Haiku rerank, OpenAI embeddings | — (no bot) | pgvector on prod K3s + `/v1/knowledge/search` (IDP-028) |
| Inference | Claude Sonnet/Haiku + OpenAI Realtime (voice), all SaaS | — | Managed (NaN cloud); ace2/Ollama is on-demand only (ADR-042) |
| Observability | Langfuse (SaaS) | — | Grafana + Loki + Vector already running; LLM dashboard IDP-025/026 |
| Design | React/Vite SPA on Vercel Edge | Brutalist-minimal, numbered sections, quantified band | Astro static (SEO) — keep |
| Conversion | "Listo para el siguiente capítulo" (hire) | "Available 2 retainer spots" (retainer) | Email capture + Beehiiv (existing Go API) |

Take: **miia chassis (clean design + quantified credibility) + santi engine (RAG bot + live dashboards), on our self-hosted data plane.** Inference is the one place we diverge from "all on-prem" — see Decision §3.

## Decision

Migrate `mlorente.dev` from a static portfolio to an **interactive-CV / living-telemetry portfolio**. Five locked choices:

1. **Frontend — evolve, do not rebuild.** Keep the existing Astro static site (preserve SEO, ~16 notes, bilingual routing, Docker→nginx→K3s pipeline) and add interactivity via **islands** (React/Solid/Preact). Server logic does NOT go in the Astro app (it is static by design); it lives in the Go API. The CV/experience timeline becomes the landing skeleton; design language moves toward miia (clean, numbered, a quantified-credibility band).
2. **Backend — adopt the ADR-043 knowledge plane.** pgvector self-hosted on prod K3s (IDP-023) → embedding pipeline honouring the allowlist (IDP-027) → `POST /v1/knowledge/search` (IDP-028) → a new `POST /v1/knowledge/chat` (ADR-029 §6) in the Go API: system prompt in Manu's 70/30 voice tuned to sell him, tool-use RAG, SSE streaming, first-person persona, rate-limit via the existing Redis.
3. **Inference — managed API, self-hosted data plane.** The chat LLM runs on a **managed API** (NaN cloud / Claude). The data plane (pgvector, search API, traces) stays self-hosted. This complies with ADR-042: nothing always-on may depend on the on-demand, UPS-less `ace2`/Ollama node, so Ollama is NOT in the public widget path.
4. **Corpus — curated allowlist.** The RAG corpus is an explicit per-directory allowlist plus a `rag: public` frontmatter flag, with ADR-043's embedding exclusions (SOPS-adjacent, `80_agents/`, `status: archived`, business strategy, employment constraints). Rationale: fail-safe vs a fail-open denylist; for an employability goal, a curated *professional* corpus is higher-signal than the whole vault. The curated set doubles as the public **knowledge garden** (proof surface PS3).
5. **Conversion — email primary, "work with me" secondary.** Omnipresent email capture is the #1 CTA (feeds YouTube + newsletter, owns the data). A single ambiguous "Work with me / Hablemos" CTA routes employment *and* consulting to one conversation. The bot may also capture email in-conversation.

Plus: a **proof-surface belt** — an *extensible* catalogue (PS1–PS7+, see Implementation) of read-only dashboards each backed by a real system Manu operates. MVP is capped (anti polish-trap): the bot + one cheap surface.

### Resolved design questions

| Question | Decision |
|---|---|
| Rebuild (React SPA) vs evolve (Astro + islands) | **Evolve.** Islands capture ~90% of the WoW without discarding SEO/content or adding a SPA to maintain. |
| Where does chat logic live | **Go API.** Astro is static by ADR; this is the correct separation, not a limitation. |
| Inference on-prem vs managed | **Managed** (ADR-042 forbids always-on dependency on on-demand nodes). Data plane stays self-hosted. |
| Corpus allowlist vs denylist | **Allowlist + `rag: public` flag.** Fail-safe; higher employability signal. |
| Observability stack | **Reuse Grafana/Loki/Vector** (+ IDP-025/026), not a new SaaS (Langfuse). Demonstrates the owned stack. |
| Proof-surface scope | **Extensible catalogue, MVP capped.** New endpoints appended to the reference doc + epic as discovered. |
| Site objective | **Email capture primary + ambiguous hire/consult secondary.** Refines (does not contradict) ADR-006's two-layer brand. |

## Options considered and rejected

- **Greenfield React/Vite (clone `cv-santiago`).** Rejected: discards the Astro SEO/content investment and adds a SPA to maintain; islands reach ~90% of the value at far lower risk.
- **Fully on-prem inference (Ollama on `ace2`).** Rejected: violates ADR-042 (on-demand, no UPS); a public widget would die when the node is off.
- **Whole-vault RAG minus a denylist.** Rejected: fail-open leak risk for private strategy/employment constraints; dilutes the employability signal.
- **Consulting-retainer-primary (miia model).** Rejected as the primary objective: Manu's goal is employability + audience-building; consulting stays secondary and inbound.

## Consequences

**Positive:** executes the existing IDP backlog rather than inventing work; the strongest possible proof-of-work (real systems shown running); owns audience data ahead of the YouTube launch; an on-brand self-hosted data plane that *is* "platform engineering for AI workloads".

**Costs / risks:**
- **IDP-023 (pgvector) is the critical-path blocker** for the bot; everything in Stream A + corpus governance + the GitHub proof surface can proceed in parallel without it.
- Corpus curation is **ongoing manual effort** (mitigated by the `rag: public` flag + directory allowlist).
- Managed inference carries **per-conversation cost** (mitigated by a small/large model split, top-K context caps, and Redis rate limits).
- Public proof surfaces require an **exposure review** per surface (no secret/PII leakage; read-only; separate ingress + rate limits).

**Inherited constraints:** ADR-042 (always-on tier = VPS; inference managed), ADR-043 (one index, one ranking, allowlist exclusions, freshness SLO ≤15 min), ADR-016 (mlorente.dev is public — no Authelia bypass needed; public endpoints are rate-limited).

## Implementation sequencing (epic WEB-010)

- **Stream A (no infra — starts immediately):** reposition `site.ts`/Hero; CV-as-landing IA + quantified band; email/funnel + ambiguous CTA; case-study template (2 from existing ADRs/lessons).
- **Stream B (backend):** IDP-023 (pgvector) → IDP-027 (pipeline, allowlist) → IDP-028 (search) → `/v1/knowledge/chat`.
- **Stream C (bot frontend):** chat island → wire to `/v1/knowledge/chat` (**MVP live**) → boundaries v1 (keyword + canary + refusal).
- **Stream D (proof surfaces):** **PS2** GitHub/OSS telemetry (cheapest, MVP); **PS1** homelab `/ops` (infra exists) and **PS3** knowledge garden (renders the curated set) in Release 2.
- **Backlog:** voice mode, evals-as-CI-gate, self-healing loop, animated architecture diagram; PS4 (DORA), PS5 (bot LLMOps), PS6 (agent activity feed), PS7+.

**Critical path:** `IDP-023 → IDP-027 → IDP-028 → /v1/knowledge/chat → C2 (bot live)`.

## Open questions

- Final inference provider (NaN open models vs Claude) — decided when building `/v1/knowledge/chat`.
- Chunking strategy + freshness SLO — inherit ADR-043 (≤15 min cron); tuned in IDP-027.
- Per-surface public exposure/auth model — separate IngressRoute + rate limit + read-only; reviewed per surface.
- The proof-surface catalogue is **explicitly open**: new interesting endpoints are appended to the reference analysis doc and the epic as they are discovered, not treated as scope creep.
