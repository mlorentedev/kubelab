---
id: "IDP-035-vikunja-n8n-task-platform"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-08-27"
issue: "mlorentedev/kubelab#1077"
tags: [spec, proposal, task-management, vikunja, n8n, slack, multi-forge, gitops]
template_version: "1.0"
---

# IDP-035: Self-Hosted Task Platform (Vikunja + n8n + Slack Multi-Forge Orchestration)

> **Naming**: file lives at `<repo>/specs/IDP-035-vikunja-n8n-task-platform/proposal.md`.

## Why

Task state across KubeLab is currently coupled to a single personal GitHub Project v2 board ("bitácora", #1). As KubeLab evolved into a hybrid multi-forge topology ([ADR-028](docs/adr/adr-028-operational-topology.md), [ADR-061](docs/adr/adr-061-stateful-service-placement.md), [ADR-065](docs/adr/adr-065-forge-repository-organization.md)), this setup became an operational bottleneck:

1. **Mono-forge lock-in**: GitHub Projects cannot natively ingest, track, or link issues/PRs from self-hosted Gitea (Beelink private repos). Private repositories remain invisible on the board.
2. **Rate limits & auth fragility**: GitHub Projects v2 relies exclusively on GraphQL. Bulk item sweeps exhaust account rate limits (lesson-007), and personal user boards require classic PAT tokens (`BITACORA_PAT`), breaking fine-grained least-privilege policies.
3. **Missing automation bus**: There is no unified mechanism to bridge multi-forge PR lifecycles, Slack ChatOps, and autonomous agent fleets (Orca ADE, CLI agents in Git worktrees).
4. **Architectural Amendment to ADR-050**: [ADR-050](docs/adr/adr-050-cross-context-command-center.md) decided to retire GitHub Projects as the task surface. While ADR-050 initially envisioned a custom Go API console, pragmatic evaluation shows adopting a lightweight self-hosted tracker (~50 MB RAM) delivers immediate multi-forge task orchestration without the maintenance debt of an unbuilt custom console. This spec executes that pivot, formalizing it via ADR-066.

## What

Deploy **Vikunja** on K3s VPS (Always-On) backed by [`infra.postgres`](docs/adr/adr-051-postgres-data-service.md) and Cloudflare R2 object storage, and configure **n8n** as the central multi-forge event bus and ChatOps orchestrator:

1. **Stateless Vikunja Deployment**:
   - Deployed to K3s prod (`infra/k8s/base/services/vikunja.yaml`) with Traefik TLS termination and edge security (`secure-headers`, `rate-limit`, `crowdsec-bouncer`) at `tasks.kubelab.live`.
   - **Native Authelia OIDC Client**: Registered in Authelia's OIDC provider ([ADR-016](docs/adr/adr-016-oidc-centralized-auth.md) / [ADR-062](docs/adr/adr-062-platform-identity-model.md)). Traefik ForwardAuth is **not** applied to `tasks.kubelab.live`, ensuring native API tokens (`Authorization: Bearer <token>`) and webhooks pass without cookie redirects.
   - **0 local PVCs**: Application is 100% stateless; relational data is stored in [`infra.postgres`](docs/adr/adr-051-postgres-data-service.md) under isolated database `vikunja`, and file uploads/avatars route directly to Cloudflare R2 ([ADR-049](docs/adr/adr-049-edge-object-storage-placement-doctrine.md)) for 24/7 global availability without homelab dependencies.
   - **Strict Resource Boundaries**: `requests: { cpu: 100m, memory: 128Mi }`, `limits: { cpu: 500m, memory: 256Mi }`. Connection pool bounded (`VIKUNJA_DATABASE_MAXOPENCONNECTIONS: 20`).
2. **SSOT Configuration in `common.yaml` & SOPS**:
   - Declared under `apps.services.core.vikunja` with environment overrides in `staging.yaml` and `prod.yaml`.
   - Secret mappings registered in `toolkit/features/k8s_secrets.py:SECRET_DEFINITIONS` (`vikunja-secrets`) and delivered via `envFrom` (ADR-038 Path 1).
3. **Idempotent Postgres Tenant Provisioner**:
   - Automated provisioning script / Job in `toolkit/features/postgres_provisioner.py` that idempotently creates role `vikunja`, database `vikunja`, and revokes access to `kubelab` database before Vikunja boots.
4. **Multi-Forge Lifecycle Synchronization Workflow (n8n)**:
   - `infra/n8n/workflows/multi-forge-sync.json`: Ingests webhooks from **both GitHub and Gitea** (`pull_request`, `push`, `issues`) with HMAC signature verification (`X-Hub-Signature-256` / `X-Gitea-Signature`).
   - Translates branch/PR names matching `AREA-NNN` into monotonic Vikunja state transitions:
     - Branch created / PR opened $\rightarrow$ Task moved to `In Progress` / `In Review`, PR URL attached via comment/patch.
     - PR merged $\rightarrow$ Task moved to `Done` (terminal state; ignores stale out-of-order events).
5. **Slack ChatOps & Notification Workflow (n8n)**:
   - `infra/n8n/workflows/slack-task-capture.json`: Ingests Slack slash commands (e.g. `/task create [title] #project`) with HMAC verification (`X-Slack-Signature`).
   - Responds to Slack within <500ms acknowledging receipt, performs async Vikunja API mutation, and updates via response URL.
   - Dispatches real-time project lifecycle notifications to `#dev-activity` via Apprise / Slack nodes ([ADR-044](docs/adr/adr-044-unified-notification-routing-fabric.md)).
6. **Agent Delegation Hook (Orca ADE / CLI Agents)**:
   - `infra/n8n/workflows/agent-dispatcher.json`: Tasks marked `agent:delegable` emit a normalized execution payload. Supports on-demand node resilience via polling/queueing when `ace2`/Beelink is powered on.
7. **Idempotent Platform Reconciler (`toolkit`)**:
   - Python reconciler `toolkit/features/vikunja.py` (`make sync-vikunja ENV=prod`) that idempotently verifies/creates default namespaces (`kubelab`, `personal`, `teledyne` per [ADR-065](docs/adr/adr-065-forge-repository-organization.md)), standard labels (`type:spec`, `type:bug`, `agent:delegable`, `priority:P0..P3`), and outgoing n8n webhooks (`changed=0` on re-run).

## Out of scope

- **Heavy monolithic trackers (Plane/Huly)**: Excluded to protect the 8 GB RAM VPS budget.
- **Custom UI rewrite**: No bespoke frontend from scratch; uses Vikunja's official Vue frontend and REST API.
- **Replacing GitHub/Gitea code hosting**: Forges continue to hold git repositories, PR reviews, and `/spec init` issue gating.

## Risks / open questions

1. **Authentication Mode (ForwardAuth vs Native OIDC)**:
   - *Risk*: ForwardAuth breaks API tokens and webhooks.
   - *Resolution*: Direct OIDC against Authelia with Traefik TLS termination. Webhooks and API tokens bypass cookie-based SSO cleanly.
2. **Gitea Webhook Egress from Beelink**:
   - *Risk*: Gitea runs on Beelink (on-demand node). Webhooks must reach n8n on VPS reliably.
   - *Resolution*: Webhooks target `https://n8n.kubelab.live/webhook/gitea` over public/Tailscale ingress with HMAC header authentication.
3. **Database Migration & User Isolation**:
   - *Risk*: Running Vikunja migrations on shared `infra.postgres` could fail if DB is missing or touch other schemas.
   - *Resolution*: Dedicated Postgres role `vikunja` granted privileges strictly on database `vikunja` (`POSTGRES_DB: vikunja`), provisioned ahead of pod boot.

## Acceptance criteria

- [ ] **AC1 — Stateless Deployment**: Vikunja runs as a `Deployment(replicas:1)` in K3s without local PVCs, connecting to `infra.postgres` (database `vikunja`) and Cloudflare R2; pod restart preserves all data without volume mount locks.
- [ ] **AC2 — SSOT & SOPS Integration**: All non-secret config lives in `infra/config/values/common.yaml` and secrets in SOPS (`vikunja-secrets`); `make deploy-k8s ENV=staging` renders manifests deterministically.
- [ ] **AC3 — Idempotent Platform Reconciler**: `toolkit/features/vikunja.py` (or `make sync-vikunja`) reconciles namespaces (`kubelab`, `personal`, `teledyne`), labels, and webhooks idempotently (`changed=0` on second run).
- [ ] **AC4 — GitHub & Gitea PR Lifecycle Sync**: Creating a PR with `AREA-NNN` on either GitHub or Gitea moves the corresponding Vikunja task to `In Review`; merging the PR moves it to `Done` with HMAC signature validation.
- [ ] **AC5 — Slack ChatOps**: A Slack command `/task create ...` creates the task in Vikunja and returns the direct link within Slack timeout limits; lifecycle events emit structured messages to Slack.
- [ ] **AC6 — Agent Delegation Trigger**: Assigning `agent:delegable` triggers the n8n agent-dispatcher workflow with normalized payload (repo, branch, spec ID) resilient to on-demand node states.
- [ ] **AC7 — Operational Runbook & ADR-066**: `docs/runbooks/vikunja-task-platform.md` documents day-to-day operations and ChatOps syntax; `docs/adr/adr-066-self-hosted-task-platform.md` formalizes the architectural transition.

## References

- ADRs: [ADR-016](docs/adr/adr-016-oidc-centralized-auth.md) (OIDC), [ADR-018](docs/adr/adr-018-ghost-cms-rejection.md) (Task placement), [ADR-028](docs/adr/adr-028-operational-topology.md) (Always-on topology), [ADR-036](docs/adr/adr-036-shared-infra-namespace.md) (`infra.*`), [ADR-044](docs/adr/adr-044-unified-notification-routing-fabric.md) (Notification fabric), [ADR-049](docs/adr/adr-049-edge-object-storage-placement-doctrine.md) (S3 placement), [ADR-050](docs/adr/adr-050-cross-context-command-center.md) (Command center & forge-agnostic board), [ADR-051](docs/adr/adr-051-postgres-data-service.md) (Postgres data-service), [ADR-061](docs/adr/adr-061-stateful-service-placement.md) (State placement), [ADR-065](docs/adr/adr-065-forge-repository-organization.md) (Forge org).
- Lessons: `lesson-007` (GitHub Projects GraphQL truncation), `lesson-093` (n8n OIDC), `lesson-013` (Secrets management).
- Upstream: Vikunja API docs (`vikunja.io/docs/api-overview`), n8n Webhook & Slack nodes.
