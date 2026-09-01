---
id: "adr-066"
type: adr
status: accepted
owner: manu
date: "2026-08-27"
issue: "kubelab#1077"
tags: [architecture, decision, task-management, vikunja, n8n, slack, multi-forge, gitops, sdd]
depends_on: [adr-016-oidc-centralized-auth, adr-028-operational-topology, adr-049-edge-object-storage-placement-doctrine, adr-050-cross-context-command-center, adr-051-postgres-data-service, adr-061-stateful-service-placement, adr-065-forge-repository-organization]
created: "2026-08-27"
---

# ADR-066: Self-Hosted Task Platform (Vikunja + n8n + Slack Multi-Forge Orchestration)

## Status

Accepted — 2026-08-27. Output of an SDD implementation session ([`specs/IDP-035-vikunja-n8n-task-platform/`](../../specs/IDP-035-vikunja-n8n-task-platform/)). Formally amends and supersedes the custom Go API console build decision of [ADR-050](adr-050-cross-context-command-center.md) (D1) by adopting a lightweight self-hosted tracker (**Vikunja**) backed by **n8n** multi-forge orchestration and **Slack ChatOps**.

## Context

Task state across KubeLab was historically coupled to GitHub Projects v2 (Board #1 "bitácora"). As KubeLab evolved into a hybrid multi-forge topology ([ADR-028](adr-028-operational-topology.md), [ADR-061](adr-061-stateful-service-placement.md), [ADR-065](adr-065-forge-repository-organization.md)), this setup broke down:
1. **Mono-forge lock-in**: GitHub Projects cannot ingest or track private repositories hosted on self-hosted Gitea (Beelink platform node).
2. **Auth and rate limit fragility**: Bulk GraphQL sweeps exhausted GitHub API rate limits (lesson-007) and required legacy user PATs.
3. **ADR-050 Realization Gap**: While ADR-050 correctly decided to retire the GitHub Projects board in favor of forge-agnostic orchestration (D3), it specced building a custom Go API console from scratch (D1). That custom console remained unbuilt, creating an operational vacuum.

Pragmatic evaluation showed that adopting **Vikunja** (~50MB RAM footprint) delivers immediate multi-forge orchestration without the maintenance burden of an unbuilt custom UI.

## Decision Drivers

- **Memory Budget**: Must fit comfortably inside the Hetzner CAX21 (8 GB ARM) VPS alongside 15+ existing services without causing cgroup OOMs.
- **Zero Sunk State / Statelessness**: Must run with 0 local PVCs in K3s, storing relational data in `infra.postgres` ([ADR-051](adr-051-postgres-data-service.md)) and file attachments in Cloudflare R2 ([ADR-049](adr-049-edge-object-storage-placement-doctrine.md)).
- **Always-On Availability (3 AM Test)**: Available 24/7 independently of homelab power states ([ADR-028](adr-028-operational-topology.md)).
- **ChatOps & Multi-Forge Ingestion**: Ingests GitHub, Gitea, and Slack events seamlessly through n8n.

## Considered Options

- **Option A**: Build bespoke Go API + Astro console (ADR-050 D1). *Rejected: heavy maintenance debt and prolonged implementation delay.*
- **Option B**: Adopt Plane / Huly. *Rejected: excessive RAM consumption (~1.8–3.5 GB) violating the 8 GB VPS budget.*
- **Option C (Chosen)**: Adopt Vikunja + n8n + Slack ChatOps. *Accepted: Go backend with Vue frontend consuming ~50 MB RAM, 0 PVCs, native OpenAPI, and instant value.*

## Decision

1. **D1 · Stateless Vikunja Deployment**:
   - Deployed as `Deployment(replicas:1)` on K3s VPS (Always-On) connecting to `infra.postgres` (database `vikunja`).
   - Resource limits strictly set: `requests: {cpu: 100m, memory: 128Mi}`, `limits: {cpu: 500m, memory: 256Mi}`.
   - Connection pool bounded to `max_open: 20`, `max_idle: 5`.
2. **D2 · Cloudflare R2 Object Storage**:
   - S3 attachments route directly to Cloudflare R2 (`service.files.type: s3`) per [ADR-049](adr-049-edge-object-storage-placement-doctrine.md), eliminating local PVC disk mounts.
3. **D3 · Native Authelia OIDC & Direct Ingress**:
   - Configured as an OIDC client against Authelia (`client_id: vikunja`).
   - Traefik ForwardAuth middleware is **not** applied to `tasks.kubelab.live`, ensuring REST API calls (`Bearer <token>`) and webhooks bypass SSO cleanly while user browser sessions authenticate via OIDC.
4. **D4 · n8n Multi-Forge Event Bus**:
   - Webhooks from GitHub and Gitea trigger monotonic state transitions (`In Progress` $\rightarrow$ `In Review` $\rightarrow$ `Done`) with HMAC signature verification (`X-Hub-Signature-256`, `X-Gitea-Signature`).
5. **D5 · Slack ChatOps & Notification Routing**:
   - `/task create` slash command parses project and priority, returns an immediate ACK in <500ms (avoiding Slack's 3000ms timeout), and updates Slack asynchronously via response URLs.
6. **D6 · Idempotent Platform Reconciler (`toolkit`)**:
   - `toolkit/features/vikunja_reconciler.py` (`make sync-vikunja`) reconciles namespaces (`kubelab`, `personal`, `teledyne` per [ADR-065](adr-065-forge-repository-organization.md)), standard labels, and webhooks idempotently (`changed=0`).

## Consequences

### Positive
- Fully self-hosted, eliminating GitHub Projects GraphQL rate limits and PAT fragility.
- 100% multi-forge parity: Gitea private repos on Beelink and GitHub public repos share the same unified board.
- Zero local PVC storage footprint on K3s.
- Low memory impact (<100MB RAM on VPS).

### Negative / Trade-offs
- Requires maintaining n8n webhook workflows as code in `infra/n8n/workflows/`.
- Postgres tenant DB `vikunja` must be backed up alongside `kubelab` database during automated backup jobs.

## Amendments

### 2026-08-31 — R2 fail-closed decision, then real credentials, then per-env bucket split (TOOL-050, #1492)

D2's Cloudflare R2 attachment storage was **deliberately made optional, not required**, as of the 1.0.0 OIDC/upgrade fix (kubelab#1506): a `VIKUNJA_FILES_S3_ENABLED: "false"` key in the base manifest, and `VIKUNJA_FILES_S3_SECRETACCESSKEY`/`ACCESSKEYID` in `k8s_secrets.py`'s `optional_keys`.

**All three of those names were wrong, and had been since IDP-035 first shipped D2.** Vikunja's actual config schema (confirmed against `pkg/config/config.go` in the 1.0.0 source) has no `files.s3.enabled` key at all — the storage backend toggle is `files.type` (`"local"`/`"s3"`), and the credential fields are `files.s3.accesskey` / `files.s3.secretkey`, not `accesskeyid` / `secretaccesskey`. Viper silently ignores config keys it doesn't recognize, so none of this ever errored — it just never did anything. Every deploy up to and including the first "re-enable R2" fix stayed on local (ephemeral `emptyDir`) storage regardless of the `ENABLED` value, which is why an uploaded attachment was downloadable (Vikunja was serving it from local disk) but never appeared in the R2 bucket. Corrected to `VIKUNJA_FILES_TYPE: "s3"` / `VIKUNJA_FILES_S3_ACCESSKEY` / `VIKUNJA_FILES_S3_SECRETKEY`, with a bucket-listing check (not just a healthy pod) as the acceptance test going forward — Vikunja's boot-time validation, observed this session, is for local storage, not S3; a healthy pod proves nothing about R2 connectivity.

Separately, once real credentials existed: an R2 API token was created for the `kubelab-vikunja` bucket, shared across staging and prod. That sharing was corrected: staging and prod now each get a **separate bucket with a separate bucket-scoped R2 token** (`kubelab-vikunja-staging` / `kubelab-vikunja`), for the same credential-blast-radius reason `kubelab-vikunja` was kept separate from the `kubelab-backups` bucket in the first place — a compromised or buggy staging deployment cannot read or write prod's attachments. R2 tokens scope to a whole bucket (no path-prefix scoping), so per-environment isolation requires per-environment buckets; there is no cheaper way to get it.

D2 closes with this fix, not the earlier ones. The `optional_keys` wiring in `k8s_secrets.py` stays as-is deliberately (fail-open on absence rather than fail-closed on a future credential rotation gap) rather than being promoted to required.

A general-purpose "staging bucket" combining file storage and backups was considered and rejected: staging has no backup mechanism today (`infra/k8s/overlays/prod/backup.yaml` is prod-only by design, "staging data is disposable"), so a shared bucket would provision for a requirement that does not exist, and would recreate the same credential-scope problem this amendment exists to fix.

## References

- [ADR-016](adr-016-oidc-centralized-auth.md) (OIDC Centralized Auth)
- [ADR-028](adr-028-operational-topology.md) (Operational Topology)
- [ADR-049](adr-049-edge-object-storage-placement-doctrine.md) (Edge Object Storage Placement)
- [ADR-050](adr-050-cross-context-command-center.md) (Cross-Context Command Center)
- [ADR-051](adr-051-postgres-data-service.md) (PostgreSQL Data Service)
- [ADR-061](adr-061-stateful-service-placement.md) (Stateful Service Placement)
- [ADR-065](adr-065-forge-repository-organization.md) (Forge Repository Organization)
