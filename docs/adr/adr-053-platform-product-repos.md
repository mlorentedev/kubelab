---
id: "adr-053"
type: adr
status: proposed
owner: manu
date: "2026-06-23"
issue: "kubelab#744"   # repo#NNN — issue-gate (per ADR-018)
tags: [architecture, decision, repo-structure, gitops, idp, platform]
created: "2026-06-23"
---

# ADR-053: Platform↔Product Repository Structure & Deployment Topology

## Status

Proposed 2026-06-23. **Extends [[adr-048-platform-consumer-repo-boundary|ADR-048]]** (which separated only the `web` frontend). Consumes [[adr-046-gitops-delivery-promotion-strategy|ADR-046]] (CI-driven promotion; Argo CD Image Updater descoped, #692) and [[adr-029-intelligence-layer|ADR-029]] (Go API as the platform gateway). Reaffirms [[adr-037-environment-promotion-strategy|ADR-037]] (conditional selfHeal per env).

## Context

ADR-048 drew the platform-vs-consumer line and extracted only the `web` frontend, leaving the general pattern unspecified. As the portfolio grows (imaging-suite, cubernautas, L3 tools…), three placement questions recur per product: where does its **code** live, where do its **K8s manifests** live, and how is a new image **promoted** into the cluster? Constraints:

- **Single operator.** Polyrepo coordination overhead is real and must be minimized (ADR-048 rationale).
- **Reusable for my own products**, not (yet) sold to clients. A scaffold / golden-path is a *consequence* of a proven pattern, not a starting point.
- **GitOps already decided** ([[adr-046-gitops-delivery-promotion-strategy|ADR-046]]): immutable tags (`sha-<short>` staging, semver prod), CI-driven promotion via `toolkit deployment promote`, Argo CD hub on AWS, staging→prod flow. Registry polling (Argo CD Image Updater) was explicitly descoped (#692) for footprint, git-honesty, and solo-operator simplicity.
- **Verified deploy reality.** mlorente.dev runs in prod on **VPS-K3s** (Deployment `web` + IngressRoute, image promoted by CI); staging runs on the homelab K3s (ace1). The API is exposed at `api.kubelab.live` (`api.mlorente.dev` is migration residue).

## Options Considered

1. **Everything per-product repo** (code + manifests + own CI/CD per product). Rejected: re-creates ADR-017's manual-sync pain; N CI pipelines and N Argo CD wirings; for one operator the overhead outweighs isolation.
2. **Everything in the kubelab monorepo** (no product repos). Rejected: keeps each product's lifecycle entangled with L0 infra; no path to a reusable per-product template.
3. **Code per-product repo; manifests centralized in kubelab; shared bases in kubelab; Argo CD app-of-apps.** Chosen. A config-repo-central pattern: kubelab is platform + config repo; products own only code + image.

## Decision

1. **Split by axis, not by project.**
   - **Product code** → its own repo (`web`, future products).
   - **K8s manifests** (overlays, domains, env) → **centralized in kubelab** (`infra/k8s`).
   - **Reusable bases** (Kustomize "a landing" base, middlewares, the golden path) → kubelab.
   - **Go API** stays in kubelab as the platform gateway, serving every product's landing (ADR-029/048).
   - **Argo CD (AWS hub)** runs app-of-apps and promotes staging→prod (the existing flow).

2. **Image promotion is push, event-driven — never polling.**
   - Each product's CI publishes an immutable `sha-<short>` image, then fires a **`repository_dispatch`** to kubelab, whose workflow runs `toolkit deployment promote` (ADR-046).
   - **Rejected — registry polling** (Argo CD Image Updater *or* an n8n registry poller). It reintroduces exactly what ADR-046 descoped (#692): a pull loop and non-git-honest state; for n8n it would also put a non-critical service on the delivery path (n8n down → no deploys). We control the image producers, so push is strictly better than pull.

3. **Pipeline events flow through the notification fabric (NOTIFY), separate from the trigger.**
   - *Delivery* (how it promotes) ≠ *observability* (how the operator finds out). Argo CD sync/health/degraded and deploy success/failure are routed via the n8n/NOTIFY fabric (Argo CD Notifications → NOTIFY-006, #685). n8n is a **notification channel, not a delivery orchestrator**.

4. **Per-repo dev/local is mandatory; the cluster is the outer loop.**
   - Each product repo ships an autonomous inner loop (`make dev` / `npm run dev`) that needs no cluster: frontend = `astro dev` pointing at the staging API via env var; API = docker-compose with local Postgres. Outer loop = staging homelab. Per-PR ephemeral previews (Argo CD ApplicationSet PR generator) are **deferred** until they hurt.

5. **The scaffold / golden-path template is distilled after 2–3 products (Rule of Three), not designed up front.**

## Rationale

For a single operator the dividing line is platform-vs-consumer (ADR-048); the cheapest maintainable shape is one config repo (kubelab) that owns deploy + shared bases, with products owning only code + image. Push-based cross-repo promotion preserves the git-honest, CI-driven delivery ADR-046 already chose instead of re-adding a poller the project deliberately removed. Centralizing manifests means the frontend dev loop carries zero Kubernetes — a concrete inner-loop win. Deferring the scaffold avoids encoding assumptions that the second product would break.

## Consequences

### Positive

- Maintainable for one operator; one source of truth for deploy.
- The reusable template emerges from real instances (Rule of Three), not speculation.
- The Go API serves all landings (multi-consumer), per ADR-029.
- Frontend development needs no cluster.

### Negative

- A change touching both frontend behavior and its manifest spans two repos (code in the product repo, overlay in kubelab).
- A cross-repo `repository_dispatch` trigger (PAT-scoped) to build and maintain.

### Neutral

- Scaffold/golden-path and per-PR previews deferred (revisit at ~3 products).
- The `api.mlorente.dev` healthcheck in `toolkit/orchestrator.py` is migration residue → cleanup task.

## References

- Extends [[adr-048-platform-consumer-repo-boundary|ADR-048]] (platform-vs-consumer boundary)
- Consumes [[adr-046-gitops-delivery-promotion-strategy|ADR-046]] (CI-driven promotion; Image Updater descoped #692)
- [[adr-029-intelligence-layer|ADR-029]] (Go API = platform gateway)
- Reaffirms [[adr-037-environment-promotion-strategy|ADR-037]] (conditional selfHeal per env)
- First implemented under WEB-020 (#697): the `web` extraction is the pilot product
