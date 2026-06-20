---
id: "adr-048"
type: adr
status: accepted
owner: manu
date: "2026-06-17"
issue: "kubelab#697"
tags: [architecture, decision, repo-structure, idp, web, api]
created: "2026-06-17"
---

# ADR-048: Platform-vs-Consumer Repository Boundary

## Status

Accepted 2026-06-17. **Supersedes [[adr-017-domain-strategy|ADR-017]]** (Two-Site Domain Strategy) and the 2026-03-14 web-architecture decision note.

## Context

KubeLab is a personal Internal Developer Platform (IDP). The repository currently mixes two concerns that have different lifecycles and ownership semantics:

1. **The platform** — infrastructure as code (K3s, Ansible, Terraform), the Go API, the deploy toolkit/CLI, and Kubernetes manifests.
2. **Consumer frontends** — `apps/web/site` (mlorente.dev, the personal-brand portfolio) and `apps/web/astro-site` (kubelab.live).

Three records disagreed on the target structure, and none matched reality:

- **ADR-017** placed both sites in the monorepo (`apps/web/portfolio/` + `apps/web/kubelab-web/` — directory names that never existed) and kept kubelab.live as a live SSR site.
- A **2026-03-14 web-architecture note** said mlorente.dev should be extracted to its own repo, killed `astro-site`, and cancelled kubelab.live (301 redirect). It also stated the Go API stays in kubelab.
- The **bitácora** carried open tickets (WEB-002b/h/i) to create a separate kubelab.live repo.

Verified reality at decision time: `apps/web/site` (package name `mlorente.dev`) is the only live frontend, statically built, no Dockerfile, not a K8s workload. `apps/web/astro-site` (package name `kubelab.live`) is dead — legacy "CubeLab" branding, stale since 2025-02, absent from CI, superseded by a `kubelab.live → mlorente.dev` 301 redirect IngressRoute. The Go API today only serves newsletter/lead-magnet endpoints (`/subscribe`, `/unsubscribe`, `/lead-magnet` via Beehiiv) for mlorente.dev, but its roadmap (WEB-016 `/v1/knowledge/chat`, IDP-025 `/v1/llm/chat`, IDP-028 `/v1/knowledge/search`) and ADR-029 ("gateway absorbed into API") make it the RAG/LLM/knowledge gateway of the platform.

## Options Considered

1. **Status quo** — everything in the kubelab monorepo. Rejected: keeps a personal-brand product entangled with L0 infra; the drift and the dead site persist.
2. **Extract web AND api** into their own repos. Rejected: the API is a platform service (the IDP gateway), not a web backend; extracting it would prevent it from serving other platform consumers, which is its explicit roadmap.
3. **Extract only the web frontends into one `web` repo; keep the platform (infra + API + toolkit/CLI) in kubelab.** Chosen.
4. **Per-domain repos** (separate mlorente.dev and kubelab.live repos). Rejected: both are frontends that share components and Tailwind config; two repos re-create ADR-017's manual-sync pain.

## Decision

- **kubelab = the platform monorepo**: infrastructure (K3s/Ansible/Terraform) + **Go API (the IDP gateway)** + toolkit/CLI + Kubernetes manifests. This is the IDP; it stays cohesive.
- **A new `web` repository holds BOTH public frontends**: mlorente.dev (EN, personal brand) and kubelab.live (ES, community). Shared components and Tailwind config live here. The `web` repo is a **consumer** of the platform: it deploys onto kubelab infra and calls `api.mlorente.dev`.
- **The Go API stays in kubelab.** It is the platform gateway, not a web BFF. The current web→API coupling is incidental (web is its first consumer); its trajectory is to serve multiple consumers.
- **The toolkit/CLI stays in kubelab** for now. Publishing it as `kubelab-cli` (PUB-001) is a later "publish when mature" move, out of scope here.
- **`apps/web/astro-site` is retired** (deleted) — it is dead code superseded by the 301 redirect. kubelab.live is rebuilt fresh inside the `web` repo at extraction time. The `kubelab.live → mlorente.dev` 301 redirect remains until the `web` repo serves kubelab.live.

## Rationale

The dividing line for an IDP is **platform vs consumer**, not code coupling. The platform is the substrate; frontends consume it. Industry prior art is consistent: platform/SRE teams keep infrastructure, platform services, and the platform CLI cohesive (the platform releases as a unit), while products with independent lifecycles and audiences get their own repos. For a single operator, polyrepo overhead (cross-repo version coordination, multiple CI pipelines, dependency drift) outweighs its benefits except for genuine consumers. One `web` repo for both domains keeps shared frontend code in one place, resolving ADR-017's documented manual-sync cost.

## Consequences

### Positive

- Single source of truth for the boundary; ends the three-way drift (ADR-017 / 2026-03-14 note / bitácora).
- The WEB-* work (interactive CV, RAG chat, conversion funnel) gets a clean home in the `web` repo, backed by the kubelab API.
- The API keeps its trajectory as the platform gateway, able to serve any consumer.
- Removing the dead `astro-site` cuts maintenance and Dependabot noise.
- Shared frontend components across both domains in one repo.

### Negative

- The `web` extraction (a separate effort) requires git-history migration, its own CI, Cloudflare deploy wiring, Dependabot, and release automation.
- A cross-repo consumer relationship (`web` → `api.mlorente.dev`) to maintain.

### Neutral

- toolkit/CLI extraction deferred (PUB-001).
- kubelab.live is rebuilt fresh rather than migrated from the retired `astro-site` (history preserves the old code if ever needed).

## References

- Supersedes [[adr-017-domain-strategy]] (Two-Site Domain Strategy)
- [[adr-029-intelligence-layer]] (gateway absorbed into API)
- Roadmap: WEB-010 (interactive CV), WEB-016 / IDP-025 / IDP-028 (API gateway), PUB-001 (kubelab-cli, deferred)
