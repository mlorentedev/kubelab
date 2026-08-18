---
id: lesson-214-homepage-services-tab-ssot-driven-dashboard-t
type: lesson
status: active
created: "2026-03-26"
owner: manu
tags: [kubelab, lesson]
---

# Homepage Services Tab — SSOT-Driven Dashboard Tables

**Context**: Building an Endpoints/Services tab for Homepage to replace the individual Staging/Prod service card tabs with consolidated HTML tables.

**Problem**: Homepage's custom.js injection pattern (DOM manipulation via hash routing) requires careful coordination between settings.yaml (layout), services.yaml.j2 (placeholders), and the sync script (JS generation). The service cards with `ping:` use Homepage's built-in backend health check, but custom HTML tables need client-side health checks.

**Solution**:
- Services tab with 3 tables (Shared/Staging/Prod) injected via `injectServices()` in custom.js
- Health checks via `fetch(url, {mode: "no-cors"})` — detects reachability but can't distinguish 200 from 500
- Category tags with click-to-filter (toggles row visibility per category)
- Column resize via mousedown drag handler, synced across all tables with same column count
- Version column extracted from `image:` tags in common.yaml via `_ver()` helper
- Diagrams split into Topology (network/DNS) + Flows (GitOps/Request/Secrets/Deploy)

**Rules**:
1. Homepage deployment/ConfigMap is NOT in Kustomize overlay — deployed via manual `kubectl create configmap` + rollout restart. Must be added to Kustomize (DASH-DT-002).
2. `make sync-homepage` runs the sync script but there's no `make deploy-homepage` yet — deploy is manual kubectl.
3. `fetch(mode: "no-cors")` resolves for ANY HTTP response (even 500) — only network errors show as "down". Not a true health check.
4. Mermaid SVGs are cached at sync-time — if mermaid.ink is down, SVGs don't regenerate. Previously rendered SVGs persist in custom.js.
5. CrowdSec in Request Path diagram must show as Traefik plugin (integrated), not separate middleware hop.
6. ace2 is a "Platform Node" (not K3s agent) since ADR-023 Phase 1 — single-node K3s on ace1.
