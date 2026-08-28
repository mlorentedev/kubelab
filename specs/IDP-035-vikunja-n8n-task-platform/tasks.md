---
tags: [spec, tasks, vikunja, n8n, slack]
created: "2026-08-27"
---

# Tasks - IDP-035: Self-Hosted Task Platform (Vikunja + n8n + Slack)

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**: `[P]` — no dependency on another unchecked task; `[AC<n>]` — helps satisfy acceptance criterion `<n>` in `proposal.md`.
>
> **Shape**: 7 atomic PRs, each ≤300 LOC cap (declarative JSON/YAML workflows and test fixtures excluded from control flow cap).

## Setup

- [x] Branch created: `feat/idp-035-vikunja-task-platform` (worktree `kubelab-vikunja-wt`)
- [x] `proposal.md` is complete and grounded with Adversarial & SRE audits
- [ ] Database role & database `vikunja` declared for `infra.postgres` in SOPS catalog

## Implementation Roadmap

### PR1 — Stateless Vikunja Deployment & Postgres Tenant Provisioning (AC1, AC2)

- [x] [P] [AC2] Write failing test: `common.yaml` validation for `apps.services.core.vikunja` (domain, OIDC, Cloudflare R2 S3, bounded connection pool `max_open=20`)
- [x] [AC2] Add `apps.services.core.vikunja` to `infra/config/values/common.yaml` and `prod.yaml`
- [x] [AC1] Implement idempotent DB provisioner helper `toolkit/features/postgres_provisioner.py` (`CREATE ROLE vikunja`, `CREATE DATABASE vikunja`, revoke access to `kubelab` DB)
- [x] [AC1] Add `SecretMapping` for `vikunja-secrets` in `toolkit/features/k8s_secrets.py` (ADR-038 Path 1)
- [x] [AC1] Create Kubernetes service manifest `infra/k8s/base/services/vikunja.yaml` (stateless deployment, `requests: {cpu: 100m, memory: 128Mi}`, `limits: {cpu: 500m, memory: 256Mi}`, connects to `infra.postgres` + R2, Traefik TLS ingress without ForwardAuth)
- [x] [AC1] Register `services/vikunja.yaml` in `infra/k8s/base/kustomization.yaml` and test render with `make deploy-k8s ENV=staging`

### PR2a — Vikunja REST API Client & Mocks in Toolkit (AC3)

- [x] [P] [AC3] Write unit tests with mock HTTP responses for `toolkit/features/vikunja_client.py` (namespaces, labels, webhooks endpoints)
- [x] [AC3] Implement typed Python `VikunjaClient` in `toolkit/features/vikunja_client.py` (granular `PATCH`, error handling, token auth)

### PR2b — Idempotent Platform Reconciler (AC3)

- [x] [P] [AC3] Write unit test for `toolkit/features/vikunja_reconciler.py`: assert `sync()` creates namespaces (`kubelab`, `personal`, `teledyne`), standard labels (`type:spec`, `priority:P0..P3`, `agent:delegable`), and outgoing n8n webhooks; assert `changed=0` on re-run
- [x] [AC3] Implement `toolkit/features/vikunja_reconciler.py`
- [x] [AC3] Add CLI command `tk task sync` and Makefile target `make sync-vikunja ENV=staging|prod`

### PR3 — n8n Multi-Forge Sync Workflow with HMAC Verification (AC4)

- [x] [P] [AC4] Write unit tests in `tests/test_n8n_multi_forge_sync.py`: assert GitHub and Gitea webhook payloads normalize correctly, validate HMAC headers (`X-Hub-Signature-256`, `X-Gitea-Signature`), and map `AREA-NNN` to monotonic Vikunja state transitions
- [x] [AC4] Implement `infra/n8n/workflows/multi-forge-sync.json` (HMAC verify $\rightarrow$ extract `AREA-NNN` $\rightarrow$ transition task $\rightarrow$ append PR URL via comment $\rightarrow$ terminal `Done` state)
- [x] [AC4] Test workflow import: `make import-n8n ENV=staging`

### PR4 — n8n Slack ChatOps & Notification Routing (AC5)

- [x] [P] [AC5] Write unit tests for Slack slash command parser (`/task create [title] #[project] [priority]`) and HMAC signature check (`X-Slack-Signature`)
- [x] [AC5] Implement `infra/n8n/workflows/slack-task-capture.json` (immediate <500ms ack to Slack $\rightarrow$ async Vikunja API mutation $\rightarrow$ response URL update)
- [x] [AC5] Wire lifecycle events to emit structured Slack notifications to `#dev-activity`

### PR5 — Agent Delegation Workflow with Queue Resilience (AC6)

- [x] [P] [AC6] Write unit test for `agent-dispatcher.json`: verify task with `agent:delegable` extracts repo, branch, spec ID, and queues/dispatches payload
- [x] [AC6] Implement `infra/n8n/workflows/agent-dispatcher.json` (formats agent execution payload, supports pull/pickup resilience when dev node is on-demand)

### PR6 — Operational Runbook & ADR-066 (AC7)

- [x] [P] [AC7] Author `docs/runbooks/vikunja-task-platform.md` (daily operations, Slack ChatOps syntax, CLI commands, backup & DR restore procedure)
- [x] [AC7] Author `docs/adr/adr-066-self-hosted-task-platform.md` formally recording the pivot from custom Go console to Vikunja + n8n

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by tests
- [x] Type checks pass (`mypy toolkit`)
- [x] Lint passes (`ruff check .`)
- [x] `verification.md` filled with real command outputs
- [ ] PRs merged deliberately under trunk-based workflow
