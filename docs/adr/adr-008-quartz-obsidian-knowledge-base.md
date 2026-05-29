---
id: "kubelab-adr-008-quartz-obsidian-knowledge-base"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-12"
owner: manu
---

# ADR-008: Quartz for Self-Hosted Obsidian Knowledge Base

## Status

Accepted (2026-02-12)

## Context

The KubeLab project maintains an Obsidian vault (`~/Projects/knowledge/`) as the single source of truth for all operational knowledge: ADRs, runbooks, troubleshooting guides, hardware documentation, and project notes. Currently this vault is only accessible via the Obsidian desktop app on the workstation.

Requirements:
1. Read-only web access to the vault from any device on the homelab network
2. Automatic sync when the vault is updated (Git push)
3. Full Obsidian feature support: `[[wikilinks]]`, backlinks, graph view, callouts, tags
4. Minimal resource usage (homelab has limited RAM)
5. Defense-in-depth security: both access control AND content filtering

## Decision

Use **Quartz** (by Jacky Zhao) to convert the Obsidian vault to a static HTML website, served by nginx:alpine behind Traefik with Authelia authentication.

### Why Quartz (over MkDocs Material, Perlite)

| Criterion | Quartz | MkDocs Material | Perlite |
|-----------|--------|-----------------|---------|
| Obsidian-native | Yes (purpose-built) | No (needs plugins) | Yes |
| Wikilinks | Native | Plugin required | Native |
| Backlinks | Yes | No | Yes |
| Graph view | Yes (interactive) | No | Yes |
| Callouts | Yes | Plugin | Yes |
| Runtime RAM | ~0 (static HTML + nginx) | ~0 (static HTML) | ~50MB (PHP) |
| Development | Very active | Very active | Low activity |

Quartz wins on Obsidian fidelity (backlinks, graph view) with zero runtime overhead.

### Security: Defense in Depth

Two independent layers protect the knowledge base:

**Layer 1 — Access control (Authelia)**:
- Traefik middleware requires Authelia SSO authentication
- Only accessible via Tailscale VPN (staging) or authenticated session (prod)
- Unauthorized users cannot reach the endpoint at all

**Layer 2 — Content filtering (Quartz)**:
- Quartz `contentIndex` configured to only publish approved folders/tags
- Sensitive notes (credentials, personal journals, private docs) excluded at build time
- Even if Layer 1 is bypassed, sensitive content is not present in the HTML output

### Sync mechanism

Cron-based (5-minute interval) for simplicity:
1. Sidecar container runs `git pull` every 5 minutes
2. If changes detected, runs `npx quartz build`
3. nginx serves the updated HTML immediately

Future upgrade path: n8n webhook trigger for instant updates (when n8n is deployed).

## Consequences

1. **New service**: `knowledge-base` in `infra/stacks/services/core/knowledge-base/`
2. **Domain**: `kb.kubelab.test` (dev), `kb.staging.kubelab.live` (staging), `kb.kubelab.live` (prod)
3. **Minimal resources**: nginx:alpine (~5MB RAM) + periodic Node.js build (only on changes)
4. **Git dependency**: vault must be in a Git repository for sync to work
5. **Content policy**: folders/tags must be explicitly approved for publication via Quartz config
6. **Obsidian Git plugin**: recommended for automatic push on vault changes

## Related

- [adr-007-vikunja-n8n-openclaw-task-delegation](adr-007-vikunja-n8n-openclaw-task-delegation.md) — n8n can provide webhook-based rebuild trigger
- [service-catalog](../architecture/service-catalog.md) — New service to register
- [deployment](../troubleshooting/deployment.md) — Deployment procedures for new service
