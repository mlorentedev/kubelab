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

Accepted — 2026-08-27. Output of an SDD implementation session ([`specs/archive/IDP-035-vikunja-n8n-task-platform/`](../../specs/archive/IDP-035-vikunja-n8n-task-platform/)). Formally amends and supersedes the custom Go API console build decision of [ADR-050](adr-050-cross-context-command-center.md) (D1) by adopting a lightweight self-hosted tracker (**Vikunja**) backed by **n8n** multi-forge orchestration and **Slack ChatOps**.

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
   - Webhooks from GitHub and Gitea, verified by HMAC signature (`X-Hub-Signature-256`, `X-Gitea-Signature`), write forward only: opening or reopening a pull request adds one comment linking it to the task and moves a task that is not yet done to the `Doing` bucket, and merging it marks the task done. An `issues` event opens a task. See the 2026-10-16 amendment for the move.
5. **D5 · Slack ChatOps & Notification Routing**:
   - `/task create` slash command parses project and priority, returns an immediate ACK in <500ms (avoiding Slack's 3000ms timeout), and updates Slack asynchronously via response URLs.
6. **D6 · Idempotent Platform Reconciler (`toolkit`)**:
   - `toolkit/features/vikunja_reconciler.py` (`make sync-vikunja`) reconciles the declared project, standard labels, and webhooks idempotently (`changed=0`).

### D6 revision — 2026-09-05: one board, not one project per organization

D6 originally read *"reconciles namespaces (`kubelab`, `personal`, `teledyne` per [ADR-065](adr-065-forge-repository-organization.md))"*. **Withdrawn.** The single board is declared at `apps.services.core.vikunja.default_project` (`Bitacora`), and every forge event routes to it.

**ADR-065 D2's argument does not transfer.** There, the organization is chosen as the axis because *"the org is the backup and retention class"* — what gets copied to R2 is answered by reading the namespace, and a third party's material never inherits a personal repository's retention policy. That reasoning is about repository **content**. A Vikunja task is *metadata about* that content, not the content, so importing the split bought none of the property it was chosen for.

**And it cost something measurable.** Vikunja's Kanban buckets are per **view**, per **project** (`pkg/models/project_view.go`). Three projects therefore meant three boards and no single "what is next" — which is the one thing the retired GitHub Project actually provided, and the reason ADR-050 D3's replacement had to be as good as the thing it replaced.

**Provenance did not disappear; it is carried twice already.** The `AREA-NNN` key is mandatory in every task title — it is the join key `GET /tasks?s=` searches on, so the integration cannot function without it — and `area:*` labels make it a filterable field. Splitting by project duplicated information that already travels in the field everything else depends on.

**What this does not decide.** Vikunja's ACL is per project, so one board means sharing is all-or-nothing. If a third party is ever given access to their own tasks, this is the decision to revisit, and the shape to revisit it with is a parent project with children — *not* a return to three peers, since that reintroduces the missing cross-cutting board. No such requirement exists today.

Consequences already applied: `multi-forge-sync` resolves the declared project by title (substituted from SSOT at import time, never read from `n8n-config` — that ConfigMap is a plain resource, so a changed key would leave the pod on the old value while Argo CD reported Synced, per lesson-404), and `DEFAULT_NAMESPACES` is retired with the `/namespaces` endpoint it targeted, which Vikunja 1.0 no longer serves (#1701).

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

### 2026-10-15 — D4 promised bucket moves the workflow never made (APP-CONFIG-010, #1687)

D4 as accepted named three transitions, `In Progress` to `In Review` to `Done`. Only the last was ever real, and by a side effect: Vikunja's update endpoint auto-moves a task to the view's done bucket when `done` flips, and moves it nowhere otherwise. The workflow computed a `targetBucket` for the other two and wrote it to nothing, while its notification and its 200 body announced it by name, three success signals for a move that did not happen.

Decision: **D4 is amended, not implemented** (option (b) of #1687). The bus performs comment-on-open and done-on-merge, and `multi-forge-sync.json` no longer computes a bucket, so nothing can announce one. Moving a task between buckets would need the Kanban view id declared in SSOT and owned by `vikunja_reconciler`, which declares none today; that is a feature with its own ticket, not a correction. The notifications had already stopped naming a bucket under APP-CONFIG-016; this removes the dead computation and makes the ADR agree.

### 2026-10-16 — The move to `Doing` is performed, to the bucket that already exists (APP-CONFIG-010, #2318)

The 2026-10-15 amendment removed the bucket moves D4 had promised and left the unbuilt half to its own ticket. The operator decided it (option B of #2318): no `In Review` bucket is created, and an opened or reopened pull request moves its task to the existing `Doing` bucket. This supersedes that amendment's "not performed" for that one transition; the rest of it stands.

The rules that keep it safe: it is forward only (a task that is already done is never moved, and a merge writes `done`, which Vikunja files in the Done bucket by itself); the bucket is a title declared once (`apps.services.core.vikunja.in_progress_bucket`) and the view and bucket are found at run time by kind and by title, never by id, because ids are per environment; a missing view or bucket fails the run and names what exists; and the notification and the 200 body name the bucket only after Vikunja's answer to the move names it too (`Confirm Move`), the failure that D4's first draft shipped. The verb is `POST /projects/{p}/views/{v}/buckets/{b}/tasks`, read from the deployed swagger: the `PUT` in the ticket creates a bucket one level up.

### 2026-10-16 — The single board is visible to its owner only; access is declared, not inherited (APP-CONFIG-013, #1701)

The D6 revision (one board, `Bitacora`, product carried by `area:*` labels) said nothing about who may see it. A Vikunja project is visible only to its owner and to whoever it is shared with, and every task n8n creates belongs to the project owner's account (`operator`), so a human signing in as `manu` saw an empty board while the workflow reported success. `make sync-vikunja` had never repaired this: it called `/namespaces`, which Vikunja 1.0 removed, and carried no credential.

Decision: **access is part of the declaration.** `apps.services.core.vikunja` declares the projects, one team and its members (keys of `apps.auth.identities`, never `machine` or `reviewer`), and the reconciler shares every declared project with that team at the declared right. Everyone sees every project for now, as in a small company; narrowing later is a change to the team or to which team a project is shared with, not an edit of N projects by M users. The reconciler authenticates with its own API token in SOPS (`apps.services.core.vikunja.reconciler_api_token`), minted by `operator` with the groups `projects`, `projects_teams`, `teams` and `labels` selected explicitly, kept apart from n8n's minimal one. It registers no webhook: the one consumer, `agent-dispatcher`, authenticates with `headerAuth` and Vikunja can only sign with an HMAC (#2326).

The client's requests are checked against Vikunja's own swagger, recorded at the deployed version (`tests/fixtures/vikunja/swagger-paths-1.0.0.json`), so an endpoint the server drops fails the suite instead of the first live run. The formal task lifecycle (states and deterministic transitions) is a separate spec.

## References

- [ADR-016](adr-016-oidc-centralized-auth.md) (OIDC Centralized Auth)
- [ADR-028](adr-028-operational-topology.md) (Operational Topology)
- [ADR-049](adr-049-edge-object-storage-placement-doctrine.md) (Edge Object Storage Placement)
- [ADR-050](adr-050-cross-context-command-center.md) (Cross-Context Command Center)
- [ADR-051](adr-051-postgres-data-service.md) (PostgreSQL Data Service)
- [ADR-061](adr-061-stateful-service-placement.md) (Stateful Service Placement)
- [ADR-065](adr-065-forge-repository-organization.md) (Forge Repository Organization)
