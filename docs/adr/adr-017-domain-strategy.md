---
id: "adr-017"
type: adr
status: active
tags: [web, domain, portfolio, content-strategy]
owner: manu
created: "2026-03-28"
---

# ADR-017: Two-Site Domain Strategy (mlorente.dev + kubelab.live)

## Status

Accepted 2026-03-03

## Context

The kubelab ecosystem needs a web presence for two distinct audiences with different languages and goals:

1. **Professional/international**: English portfolio, technical notes, consulting CTA — targeting recruiters, potential clients, and the global platform engineering community.
2. **Content/community**: Spanish blog, YouTube content, newsletter, infoproducts — targeting the Spanish-speaking tech community (cubernautas audience).

A single domain serving both audiences creates friction: mixed-language content confuses SEO, forces UI language toggles, and dilutes the brand identity of each channel.

### Options Considered

1. **Single site with i18n** (`mlorente.dev/en`, `mlorente.dev/es`): Simpler infra, but forces a single brand identity. Spanish content hub (YouTube, newsletter) doesn't fit under a personal portfolio domain.
2. **Subdomain split** (`portfolio.kubelab.live`, `blog.kubelab.live`): Keeps one domain, but `kubelab.live` is the project brand, not the person. Recruiters expect a personal domain.
3. **Two separate domains** (`mlorente.dev` EN, `kubelab.live` ES): Clean separation of identity, audience, and purpose. Each site optimized for its audience. Cross-linked in footer.

## Decision

**Option 3: Two separate domains, two separate Astro projects.**

| Domain | Language | Purpose | Output | Project |
|--------|----------|---------|--------|---------|
| `mlorente.dev` | EN | Professional portfolio + /notes technical blog | Static (pre-rendered) | `apps/web/portfolio/` |
| `kubelab.live` | ES | Blog, YouTube, newsletter, infoproducts | SSR (Node adapter) | `apps/web/kubelab-web/` |

### Key design choices

- **mlorente.dev is static**: No backend needed. Pre-rendered HTML, deployed to any CDN or static host. Zero JS dependencies.
- **kubelab.live remains SSR**: Needs dynamic features (newsletter signup, API calls, feature flags).
- **Cross-link in footer**: Each site links to the other with clear language/purpose context ("Blog en español → kubelab.live").
- **Shared infra**: Both deploy on the same K3s cluster via Traefik IngressRoutes. DNS already managed in Cloudflare.
- **Content collections**: mlorente.dev uses MDX content collections for /notes (English technical articles). kubelab.live uses its existing blog collection (Spanish).

## Consequences

### Positive

- **SEO clarity**: Each domain targets one language and audience. No hreflang complexity.
- **Brand separation**: Personal professional identity (mlorente.dev) vs project/community identity (kubelab.live).
- **Independent deploy cycles**: Portfolio changes don't risk breaking the content site and vice versa.
- **Static portfolio is fast and cheap**: No server process, works on any CDN, near-zero operational cost.

### Negative

- **Two projects to maintain**: Shared Tailwind config and component patterns must be kept in sync manually (no shared package yet).
- **Duplicate base components**: Header/Footer/Layout patterns will be similar but not identical across both sites.
- **DNS configuration**: Two domains in Cloudflare, two sets of IngressRoutes in K8s.

### Risks

- **Content drift**: English notes on mlorente.dev and Spanish blog on kubelab.live may cover the same topics. Mitigated by the Content Strategy below.

## Content Strategy (added 2026-03-04)

Clear separation of what goes where. The rule: **never translate one into the other.**

| Content type | Destination | Language | Example |
|---|---|---|---|
| Opinions, decisions, war stories | mlorente.dev/notes | EN | "Why I run K8s on bare metal instead of EKS" |
| Runbooks, technical references | mlorente.dev/notes | EN | "How I debug a failing K3s node in 5 minutes" |
| Tutorials, step-by-step guides | kubelab.live | ES | "Cómo montar un clúster K3s en bare metal" |
| CS fundamentals, educational | kubelab.live | ES | "Big O Notation explicado con ejemplos" |
| YouTube companion posts | kubelab.live | ES | Episode notes, show links |
| Newsletter, infoproducts | kubelab.live | ES | Courses, paid content |

### Tone

- **mlorente.dev**: Direct, opinionated, Hormozi-style. Short pieces (800-1500 words). Demonstrates expertise to CTOs evaluating whether to hire or engage. Copy must feel human and have character — not corporate.
- **kubelab.live**: Educational, approachable, community-focused. Longer pieces. Teaches, doesn't sell.

### Legacy content

Old Jekyll blog posts (Big O, algorithms, estimations, scaling) are educational CS fundamentals — they belong in kubelab.live (ES), translated and adapted. Not in mlorente.dev/notes.

## References

- ADR-018: Ghost CMS Rejection
- Portfolio master index: `30-architecture/portfolio.md`
- WEB-001 task in `11-tasks.md`
