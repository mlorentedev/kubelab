---
id: "adr-066"
type: adr
status: accepted
owner: manu
date: "2026-08-27"
issue: "kubelab#1077"
tags: [architecture, decision, task-management, vikunja, n8n, slack, multi-forge, gitops, sdd]
depends_on: [adr-016-oidc-centralized-auth, adr-028-operational-topology, adr-049-edge-object-storage-placement-doctrine, adr-050-cross-context-command-center, adr-051-postgres-data-service, adr-061-stateful-service-placement, adr-065-forge-repository-organization, adr-057-kubelab-api-boundaries, adr-067-product-contract-and-agent-access, adr-073-self-service-resource-claims]
created: "2026-08-27"
---

# ADR-066: Self-Hosted Task Platform (Vikunja + n8n + Slack Multi-Forge Orchestration)

## Status

Accepted — 2026-08-27. Output of an SDD implementation session ([`specs/archive/IDP-035-vikunja-n8n-task-platform/`](../../specs/archive/IDP-035-vikunja-n8n-task-platform/)). Formally amends and supersedes the custom Go API console build decision of [ADR-050](adr-050-cross-context-command-center.md) (D1) by adopting a lightweight self-hosted tracker (**Vikunja**) backed by **n8n** multi-forge orchestration and **Slack ChatOps**.

**Status note — 2026-10-20.** The 2026-10-20 amendment below reverses this ADR's central choice. Forge issues and pull requests are the task surface, the view over them is a cross-forge read model in the kubelab API, and Vikunja is retired. D1-D6 and the four earlier amendments stay as the record of what was deployed and why; they no longer describe the target. Of the Decision Drivers, the memory budget, zero PVCs and always-on still bind; the fourth is restated in A5.

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

### 2026-10-20 — Forge issues and pull requests are the task surface; Vikunja is retired (CONSOLE-004, #2570)

**Context.** The operator decided on 2026-10-20 that Vikunja is not the tracker. For an SRE the tasks are issues and pull requests, a separate tracker duplicates state the forge already holds, and Vikunja's interface is built for personal to-do lists. What was used and valued in the GitHub Project was only the view: items from every repository, grouped and sorted by state, with quick actions. Epics, milestones and roadmap views are not needed. The view must converge GitHub and Gitea, GitLab later, and be showable as part of the IDP.

Three facts measured in the repository shape the decision:

- **The duplication is the integration.** Every amendment above corrects a seam between two copies of one state: the `AREA-NNN` join key a title must carry, a substring search that needs an exact-match guard, a failed search that must not read as empty, bucket moves announced and not made. A view that reads the forge has no seam to correct.
- **Vikunja is deployed but not load-bearing.** The issue-to-task path (#1684) and dotfiles#1424 are still open. The footprint is not small: 160 files mention it (counted 2026-10-20, archived specs and lessons included), among them the manifests, the SSOT block, the SOPS catalog, the OIDC clients, three n8n workflows, the reconciler, its client and their tests.
- **The GitHub Projects board was never retired.** [ADR-050](adr-050-cross-context-command-center.md) D3 retired it and this ADR's Context describes it as replaced, but `add-to-project.yml`, `bitacora-status.yml` and `toolkit/features/board_*.py` are live. dotfiles ADR-018 and `AGENTS.md` name the board the SSOT for task state, and the harness skills write its Status and Priority fields. Two ADRs recorded a retirement that did not happen; A4 states what actually happens to it.

**A1 · The forge is the task surface, and Status and Priority are labels.**

- An item is an issue or a pull request in its home repository. Open, closed and merged are the forge's own state and are never copied into a label.
- Priority is `priority:P0` to `priority:P3`, the names `DEFAULT_LABELS` in `toolkit/features/vikunja_reconciler.py` already declares. `type:spec|bug|chore`, `agent:delegable` and `area:<AREA>` (`apps.services.core.vikunja.labels.areas` in `common.yaml`) carry over unchanged.
- Status beyond open and closed is new, because no `status:*` label exists today; on GitHub, Status is a board field. Two labels: `status:in-progress` and `status:blocked`. Backlog is an open item with neither; in review is derived from an open pull request that closes the issue; done is closed or merged.
- The label set is declared once in `common.yaml` and reconciled onto each forge, never created by hand. The Gitea side extends the existing Gitea reconciler (`toolkit/features/gitea_repos.py`); nothing reconciles GitHub labels today, so that reconciler is new work the spec names.
- **Why labels, not fields.** A label is the one issue field GitHub, Gitea and GitLab all carry. `pattern-bitacora-project-setup` (knowledge store) makes Priority a field because labels do not sort in the Projects table view. That reason was a property of a UI this decision stops using: the read model sorts.
- **Not verified here:** the live label sets on the GitHub repositories and the Gitea organizations. The spec inventories them before the first reconcile.

**A2 · The view is a thin cross-forge read model inside `apps/api`.**

- **Placement.** A module of the kubelab API: a cross-cutting platform surface, not product logic ([ADR-057](adr-057-kubelab-api-boundaries.md) D3), in the existing binary rather than a new service (D2). Where the console is served and what its REST surface looks like is decided by ADR-074 (#2477); if it places the console outside `apps/api`, this module follows it.
- **Per-forge read adapters**, in Go, behind one interface. GitHub and Gitea first; GitLab is a third adapter, not a redesign. This keeps ADR-050 D3's adapters. It is not a port of the toolkit's Python Gitea client, which reconciles forge configuration rather than reading issues ([ADR-034](adr-034-polyglot-apps-language-per-service.md); [ADR-073](adr-073-self-service-resource-claims.md) D11, the language boundary is data, not calls).
- **The read model** is a projection in an `infra.postgres` tenant ([ADR-051](adr-051-postgres-data-service.md)): one row per item (forge, repository, number, kind, title, state, labels, assignees, updated time, URL) plus per-source freshness (A6). It is a cache, rebuildable from the forges at any time, so it is `dual` under [ADR-061](adr-061-stateful-service-placement.md) and losing it loses nothing.
- **The event outbox** has two directions. Inbound, a webhook verified by its HMAC signature (D4's verification, moved here) is appended to an event table before it is projected, so a projection failure replays instead of losing the event, and a periodic reconcile read per source repairs missed deliveries. Outbound, every quick action is an outbox row with an idempotency key, delivered to the forge and shown as pending until the forge's answer confirms it. Nothing is announced before the forge confirms it, the failure the 2026-10-15 amendment records.
- **Narrow writes only:** add or remove a declared `status:*` or `priority:*` label, assign or unassign, close or reopen an issue. No merge, no review, no approval, no branch and no content edit. Merging stays on the forge under the merge rules. Every write is attributed to the signed-in identity and to a forge token scoped to issues, separate from the read token; both live in SOPS and in `SECRET_CATALOG`.
- **Access.** `apps/api` has no authentication today (ADR-073), and the read model holds private repository titles. The route sits behind Authelia before the first private source is read.
- **Visibility.** Each source carries a visibility class derived from its forge organization ([ADR-065](adr-065-forge-repository-organization.md) D2: the organization is provenance). An organization holding a third party's material (ADR-065 D2's example) is never rendered in the demo view and never reaches an LLM without the per-context grant ([ADR-050](adr-050-cross-context-command-center.md) C1, C2, D5). That partition is what makes the view showable as part of the IDP.

**A3 · Vikunja is retired, not demoted.**

Demoting it to a tracker for personal tasks that have no forge issue was considered and rejected. Its own driver, multi-forge orchestration, moves to A2. The operator does not want a second tracker, and no requirement for items without an issue exists today: ADR-050 D3's "native items" were the one thing only Vikunja could hold, and nobody uses them. Demotion would keep everything retirement removes (a Deployment, the `vikunja` database, two R2 buckets with their tokens, an OIDC client pair, the reconciler and its tests) for a use that was declined.

The retirement follows AI-007 (Ollama) and OPS-023 (MinIO): remove the manifests, the SSOT block, the SOPS keys and catalog entries, the OIDC client pair (#2557 is the precedent), the break-glass, NetworkPolicy, error-pages and DNS entries for `tasks.kubelab.live`, `make sync-vikunja` and its toolkit modules, the swagger fixture, the runbook, and `multi-forge-sync`, `slack-task-capture` and `agent-dispatcher` with their import specs. A test then keeps it gone, as `tests/test_no_live_minio_references.py` does. The only state Vikunja holds that no forge holds is tasks created outside the forge path, from Slack or in its UI; one final database dump goes to the backup bucket before the database is dropped. The R2 buckets and their tokens are not in git and Argo CD does not prune them, so the change names their deletion as an operator step.

**A4 · The GitHub Projects board stays until the view reaches parity, then retires in one step.**

- **Until parity**, the board remains the GitHub-only view and its fields remain authoritative for GitHub items. The read model shows GitHub items without board-only Status or Priority until then; it is not yet in use, so the gap costs nothing.
- **Parity** means every repository the board aggregates, grouped by status, sorted by priority, with the quick actions in A2.
- **The step:** backfill each open item's board Status and Priority into labels once, switch the writers to labels, then delete `add-to-project.yml`, `bitacora-status.yml` and `board_*.py`. Doing it in one step avoids two truths for the same field.
- **The step is gated outside this repository.** dotfiles ADR-018 and `AGENTS.md` make the board the SSOT, and `/new-ticket` and `/handoff` write its fields. Those change first, or the board retires under live writers.
- **`multi-forge-sync` retires with Vikunja** (A3). Its signature checks and the event subscriptions declared in `apps.services.core.gitea.webhook.events` move to the read model's webhook receiver. n8n keeps the notification fabric ([ADR-044](adr-044-unified-notification-routing-fabric.md)) and leaves the task path, which also narrows what ADR-061 D3's n8n `dual` condition has to cover.
- **D5's Slack `/task create` is not carried over.** Capturing a task is opening an issue. If capture from Slack is wanted again, it is a request for one more narrow write, not a tracker.

**A5 · The Decision Drivers, re-read against the new design.**

- **Memory budget: holds and improves.** Vikunja's 128 Mi request and 256 Mi limit leave the VPS, and the module runs inside a pod that already exists. The spec measures the API pod's memory before and after.
- **Zero PVCs: holds.** The read model and the outbox live in `infra.postgres`, and attachments stay on the forge, so the R2 buckets go.
- **Always-on: holds for the view**, which runs on prod. It does not hold for every source, which is A6.
- **ChatOps and multi-forge ingestion: restated.** Ingestion stays, as webhooks plus a reconcile read, but it lands in the read model instead of passing through n8n into a tracker. ChatOps leaves the task path.

**A6 · An unreachable forge is never rendered as an empty one.**

Gitea runs on the Beelink, which is on-demand ([ADR-028](adr-028-operational-topology.md), ADR-061 D2), so the view must say when a source is down.

- Each source carries `as_of`, the time of its last successful full read, and `source_reachable`, the result of its last attempt.
- A source that cannot be read shows its last known items marked stale with their `as_of`, or, if it was never read, an explicit unreachable state. It never shows zero items. This is the rule ADR-067 D6 sets for `toolkit-mcp` (staging spokes are reported unreachable, not failed) and the one `multi-forge-sync` already follows (a failed search is not an empty search).
- A write against an unreachable source stays in the outbox and is shown as pending. It is neither dropped nor reported done.
- When a source comes back, it is read in full before its items lose the stale mark.

**A7 · The boundary with ADR-074 (#2477).**

One console, two modules, two sources of truth. The platform console (ADR-073 D11's portal, decided by ADR-074) shows the product registry: owners, links into Argo CD and Grafana, and golden-path actions that open PRs. It reads what the toolkit writes to git. This view shows the forge: issues and pull requests, read from the forges. Neither module reads the other's source. Where they meet is a link: the registry maps an app to its repository ([ADR-067](adr-067-product-contract-and-agent-access.md) D2), so a product page may link to that repository's items here, by URL and filter rather than by a shared store.

**A8 · Kill criteria.** Timebox five working days for the queue view, the narrow writes and the call budget, on Gitea alone. If the operator does not open the surface on at least 5 of 14 consecutive days after it ships, the setup reverts to the previous one and #2570 closes with that evidence.

**Hold list.** #1684 and dotfiles#1424 are paused until this amendment merges, because both are open work on the Vikunja integration it retires; after the merge they are closed or rewritten against the view. #503 and #2523 proceed either way.

**Alternatives considered.**

- **Keep Vikunja as the tracker.** Rejected: it holds a second copy of state the forge owns, and every earlier amendment is a correction of that seam.
- **Demote Vikunja to tasks with no forge issue.** Rejected (A3).
- **Keep the GitHub Project as the view.** Rejected: it is GitHub-only and cannot hold a Gitea or GitLab item, ADR-050 D3's reason, which still holds.
- **ADR-050 D3 as written: a board that owns status and priority in its own store.** Rejected: it recreates the second copy this amendment removes. Its per-forge adapters survive (A2); its ownership of state does not.
- **n8n workflows projecting into Postgres, with Grafana as the view.** Rejected: Grafana holds no ownership and opens no actions (ADR-073 D10), and n8n's workflow promotion path is special-cased (ADR-061 D3).
- **A separate service for the view.** Rejected at the current scale (ADR-057 D2 and D4), unless ADR-074 decides otherwise.
- **A page rendered by CI into git.** Rejected: one commit per poll, freshness bounded by a cron, and no writes.
- **Each forge's own board.** Rejected: no single view, which is the original problem.
- **Adopting an existing tool.** No suitable open-source tool was found; see the maintainer's knowledge store.

**Reopen triggers.**

- A class of task appears that no forge issue fits, and the operator wants it in the same view: revisit A3's demotion.
- The reconcile read measurably exceeds a forge's API budget: revisit the poll interval and webhook coverage. Read #1501's measurement first; this amendment states no GitHub API limit.
- ADR-074 places the console outside `apps/api`: A2's placement follows it.
- Epics, milestones or roadmap views become a requirement.

**Not amended here, recorded so the silence is not read as an oversight.** ADR-050's status note still says D1 was superseded by this ADR. With Vikunja retired, D1's Go API and console surface is reinstated in the narrowed form of A2, and D3's ownership of state is rejected, which also makes ADR-073 D11's "ADR-050 keeps D1" consistent again. That note, `pattern-bitacora-project-setup` in the knowledge store and dotfiles ADR-018 are updated in their own changes.

## References

- [ADR-016](adr-016-oidc-centralized-auth.md) (OIDC Centralized Auth)
- [ADR-028](adr-028-operational-topology.md) (Operational Topology)
- [ADR-049](adr-049-edge-object-storage-placement-doctrine.md) (Edge Object Storage Placement)
- [ADR-050](adr-050-cross-context-command-center.md) (Cross-Context Command Center)
- [ADR-051](adr-051-postgres-data-service.md) (PostgreSQL Data Service)
- [ADR-061](adr-061-stateful-service-placement.md) (Stateful Service Placement)
- [ADR-065](adr-065-forge-repository-organization.md) (Forge Repository Organization)
- [ADR-034](adr-034-polyglot-apps-language-per-service.md), [ADR-044](adr-044-unified-notification-routing-fabric.md), [ADR-057](adr-057-kubelab-api-boundaries.md), [ADR-067](adr-067-product-contract-and-agent-access.md), [ADR-073](adr-073-self-service-resource-claims.md) (cited by the 2026-10-20 amendment)
- kubelab#2570 (CONSOLE-004), #2477 (ADR-074, console REST surface), #1684, #1501, #503, #2523, dotfiles#1424
