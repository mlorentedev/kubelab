---
id: kubelab-agents
type: architecture
status: active
created: "2026-05-09"
---

# kubelab-agents (component spec)

> **Status:** `spec` — no code yet. Lives here as a design doc until promotion criteria are met.
>
> ⚠ **STALE-AS-OF 2026-05-15:** OpenClaw runtime replaced by Hermes (Nous Research). Component pending rename to `kubelab-orchestrator` per ADR-034 (draft). All references to OpenClaw below to be rewritten in cascade rewrite session. See 2026-05-15-orchestrator-pivot for decisions + cascade inventory.
> **Parent:** kubelab
> **Layer:** L1-platform
> **ADRs:** [ADR-007](../../adr/adr-007-vikunja-n8n-openclaw-task-delegation.md) (full vision) · [ADR-022](../../adr/adr-022-openclaw-agent-deployment.md) (MVP refinement) · [ADR-028](../../adr/adr-028-operational-topology.md) · [ADR-029](../../adr/adr-029-intelligence-layer.md)

## Problem

Manual task execution doesn't scale. Repetitive tasks (log triage, content drafts, dependency updates, monitoring responses) consume time that could be delegated to AI agents — with appropriate human oversight for different risk levels.

More immediately: knowledge capture is manual. Articles, ideas, and notes forwarded via messaging apps get lost or require manual processing into the Obsidian vault.

## Solution

Phased approach — start with a personal AI assistant, evolve into full task delegation:

### Phase 0 — MVP: Personal Assistant + Knowledge Capture
- **OpenClaw** on Beelink (Docker, sandboxed, 2GB mem limit)
- **Telegram** as primary input (forward articles, ideas, notes)
- **Hive MCP** for vault access (read everything, write only to `80_inbox/`)
- **Ollama local** (Qwen2.5:1.5b for tagging, 7b for content) + **OpenRouter** (Opus for complex, Gemini Lite for cronjobs)
- **Budget:** $5-10/week on OpenRouter (dedicated API key with spending cap)
- **Output:** Processed, tagged, frontmatter-compliant notes in `80_inbox/` for human review and promotion

### Phase 1 — Scheduled Workflows
- **n8n** as multi-source ingestion (RSS feeds, email forwarding, GitHub webhooks)
- Cronjobs: daily digest, feed processing, reminders
- Gemini Lite via OpenRouter for cheap scheduled tasks

### Phase 2 — Task Delegation (ADR-007)
- **Vikunja** for task management with `agent:delegable` labels
- Full human-in-the-loop workflow via Slack
- Autonomy levels L1-L3 per task type

## Tech Stack

| Component | Technology | Phase |
|-----------|------------|-------|
| Agent runtime | OpenClaw (Docker, sandboxed) on Beelink | 0 |
| Input | Telegram (native OpenClaw support) | 0 |
| Vault access | Hive MCP server (vault clone on Beelink) | 0 |
| Local LLM | Ollama on Beelink (Qwen2.5:1.5b, 7b, on-demand) | 0 |
| Cloud LLM | OpenRouter (Opus, Gemini Lite) — dedicated API key | 0 |
| Workflow engine | n8n (self-hosted, already in staging) | 1 |
| Task management | Vikunja (self-hosted) | 2 |
| Communication | Slack (interactive messages, approve/reject) | 2 |

## Dependencies

- kubelab L0 (K3s, staging operational) ✓
- Beelink provisioned with Docker + Ollama ✓
- Hive MCP server (v1.11.5 shipped) ✓
- OpenRouter account + dedicated API key
- Vault clone + git sync cron on Beelink

**Deferred dependencies (Phase 2+):**
- [kubelab-gateway](kubelab-gateway.md) (LLM routing — absorbed into kubelab API by ADR-029, OpenRouter covers MVP)
- [kubelab-memory](kubelab-memory.md) (agent persistent memory — absorbed by ADR-029, Hive covers MVP)

## Decisions

| Decision | Choice | Reason | Date |
|----------|--------|--------|------|
| Task system | Vikunja (not Jira/Linear) | Self-hosted, SSO-ready, webhook API, lightweight | 2026-02-08 |
| Workflow engine | n8n (not Temporal/Airflow) | Already in service catalog, visual builder, webhook triggers | 2026-02-08 |
| Agent hosting | RPi 4 bare metal | 8GB, no GPU needed (uses external LLM APIs), separate blast radius | 2026-02-08 |
| LLM strategy | DeepSeek (bulk) + Claude (premium) + local (free) | Cost optimization via gateway routing | 2026-02-08 |

## Milestones (component-level)

| # | Milestone | Done criteria | Phase | Status |
|---|-----------|---------------|-------|--------|
| 1 | OpenClaw on Beelink | Docker container running, Telegram connected, Ollama accessible | 0 | [ ] |
| 2 | Hive vault integration | Vault cloned, Hive MCP running, read all + write `80_inbox/` verified | 0 | [ ] |
| 3 | Knowledge capture pipeline | Forward article via Telegram → processed note in `80_inbox/` with correct frontmatter | 0 | [ ] |
| 4 | OpenRouter integration | Opus for complex tasks, Gemini Lite for simple, spending cap enforced | 0 | [ ] |
| 5 | n8n ingestion workflows | RSS, email, GitHub webhook → OpenClaw → `80_inbox/` | 1 | [ ] |
| 6 | Scheduled tasks | Daily digest, reminders, feed processing via n8n cronjobs | 1 | [ ] |
| 7 | Vikunja deployed | SSO via Authelia, projects/labels configured, webhooks to n8n | 2 | [ ] |
| 8 | Task delegation pipeline | End-to-end: task create → decompose → execute → checkpoint → approve → done | 2 | [ ] |

## Lifecycle

| Transition | Trigger | Date |
|------------|---------|------|
| → idea | ADR-007 (Vikunja + n8n + OpenClaw) | 2026-02-08 |
| → spec | Streams F + H fully defined in kubelab todo.md | 2026-02-08 |
| → refined | ADR-021 (phased approach, Beelink, inbox pattern) | 2026-03-15 |

## Backlog (when promoted)

> Full task breakdown preserved from the previous standalone roadmap. Source of truth for F1-F4, H2-H4, and the Content Generation pipeline. To execute when this component is prioritized and promoted to `10_projects/kubelab-agents/`.

### F1: Vikunja Deployment

> Blocked by: kubelab B5 (staging operational)

- [ ] **VIK-001**: Create Vikunja stack (`infra/stacks/services/core/vikunja/`)
  - `compose.base.yml`: Vikunja + PostgreSQL (or shared instance)
  - `compose.dev.yml`, `compose.staging.yml`, `compose.prod.yml`
- [ ] **VIK-002**: Add Vikunja config to `infra/config/values/common.yaml`
  - Domain: `tasks.kubelab.test` / `tasks.staging.kubelab.live` / `tasks.kubelab.live`
  - Resource limits, OIDC config (Authelia), SMTP for notifications
- [ ] **VIK-003**: Add Traefik route for Vikunja
  - Update templates or add to generated config
  - Authelia middleware for SSO login
- [ ] **VIK-004**: Deploy and verify Vikunja locally
  ```bash
  toolkit services up vikunja
  curl -I https://tasks.kubelab.test
  ```
- [ ] **VIK-005**: Configure initial project structure in Vikunja
  - Projects: `kubelab/infra`, `kubelab/apps`, `trabajo`, `personal`
  - Labels: `agent:delegable`, `priority:high`, `priority:low`, `checkpoint:per-subtask`, `checkpoint:final-only`
  - Custom states: `pending`, `agent_working`, `checkpoint`, `approved`, `done`
- [ ] **VIK-006**: Configure Vikunja webhooks
  - Webhook on task create/update → n8n endpoint
  - Filter: only fire for tasks with `agent:delegable` label

**Done when**: Vikunja accessible via HTTPS, SSO via Authelia, projects and labels configured, webhooks pointing to n8n endpoint.

### F2: n8n Agent Pipeline Workflow

> Blocked by: F1 + n8n deployed

- [ ] **N8N-001**: Design n8n workflow "Agent Task Pipeline"
  - Webhook trigger (Vikunja task event)
  - Validate `agent:delegable` label
  - Extract YAML agent context from task description
  - Error handling: malformed YAML → Slack notification to user
- [ ] **N8N-002**: Implement decomposition phase
  - Call OpenClaw API: "Decompose this task"
  - Receive proposed subtasks
  - Create subtasks in Vikunja via API
  - Slack notification: "Agent proposes N subtasks. Approve?"
  - Wait for callback (Slack button or Vikunja state change)
- [ ] **N8N-003**: Implement execution loop
  - For each subtask: call OpenClaw API, update Vikunja state, pause at checkpoint, notify Slack with artifacts
  - Wait for human approval; on reject: notify agent, allow revision
  - Timeout: if no agent progress in X minutes → pause + Slack alert
- [ ] **N8N-004**: Implement completion phase
  - All subtasks approved → mark parent task as Done in Vikunja
  - Slack summary: "Task completed. N subtasks, M checkpoints, T tokens used."
  - Audit log entry (tokens consumed, duration, artifacts)
- [ ] **N8N-005**: Slack interactive messages
  - Approve/Reject buttons on checkpoint notifications
  - Comment field for feedback to agent
  - Thread grouping: one Slack thread per parent task

**Done when**: End-to-end workflow works in n8n — task creation triggers decomposition, agent executes with checkpoints, human approves via Slack, task marked done.

### F3: Agent Deployment on RPi 4

> Blocked by: B0 (RPi 4 provisioned as gateway). Can run parallel with F1.
> Agents run on RPi 4 (`kubelab-rpi4`, 8GB) — no GPU needed, uses external LLM APIs.

- [ ] **CLAW-001**: Evaluate OpenClaw + PicoClaw deployment requirements
- [ ] **CLAW-002**: Deploy OpenClaw on RPi 4 (Docker or native Node.js)
- [ ] **CLAW-003**: Deploy PicoClaw on RPi 4 (Docker or Go binary)
- [ ] **CLAW-004**: Configure n8n → OpenClaw pipeline (n8n on Acemagic calls OpenClaw on RPi 4 over LAN/Tailscale)
- [ ] **CLAW-005**: Configure multi-repo agent access
  - Git credential helper for agent containers
  - Per-repo access list (configurable via Vikunja task context)
  - Security: agents NEVER get access to SOPS keys, production credentials, or infra repos unless explicitly allowed
- [ ] **CLAW-006**: Test agent execution in isolation (test repo, verify branching/PR + isolation guarantees)

**Done when**: OpenClaw + PicoClaw running on RPi 4, accessible via LAN/Tailscale, agents use DeepSeek/OpenRouter for LLM, isolation verified.

### F4: Integration Testing

> Blocked by: F2 + F3

- [ ] **INT-F01**: End-to-end simple single-subtask flow
- [ ] **INT-F02**: Multi-subtask with `checkpoints: per-subtask`
- [ ] **INT-F03**: Rejection and revision flow
- [ ] **INT-F04**: Timeout handling (simulate agent hang → Slack alert)
- [ ] **INT-F05**: Verify non-delegable tasks unaffected
- [ ] **INT-F06**: Multi-repo test (task targeting repo outside kubelab, e.g. sensortool)

**Done when**: All integration tests pass. Delegable and non-delegable tasks coexist. Slack communication bidirectional. Timeout and rejection flows work.

### H2: Task Catalog & Autonomy Classification

- [ ] **CAT-001**: Define task catalog with autonomy levels
  - **L3 (autonomous)**: log triage, uptime alert response, scheduled reports, data scraping, RSS digest
  - **L2 (checkpoint)**: content drafts, PR reviews, dependency updates, config changes
  - **L1 (assist only)**: architecture proposals, security-related changes, infra modifications
- [ ] **CAT-002**: Implement autonomy enforcement in n8n
  - L3: agent completes → logs result → no human needed
  - L2: agent completes → pauses → Slack approval → continues
  - L1: agent proposes → human implements → agent not involved in execution
- [ ] **CAT-003**: Define guardrails per level
  - L3 guardrails: max execution time, no git push, no external API calls beyond whitelist, output size limits
  - L2 guardrails: same as L3 + diff size limit, mandatory PR (no direct push)
  - Blast radius: agent containers have no access to prod, SOPS keys, or infra repos

### H3: Always-On Agent Loops

- [ ] **LOOP-001**: Monitoring response loop (Uptime Kuma alert → triage → auto-remediate or escalate)
- [ ] **LOOP-002**: Daily digest loop (07:00: RSS, GitHub notifications, calendar, Vikunja backlog → Slack/Telegram briefing). LLM tier: DeepSeek
- [ ] **LOOP-003**: Content pipeline loop (Vikunja `content:draft` label → draft → blog repo branch → Slack review). LLM tier: DeepSeek + Claude polish
- [ ] **LOOP-004**: Data analysis loop (weekly Prometheus/Grafana metrics summary, anomaly flags)

### H4: Scaling & Evaluation

- [ ] **EVAL-001**: Agent effectiveness metrics (autonomous vs intervention, time saved, error rate, cost per task type)
- [ ] **EVAL-002**: Weekly agent review ritual (promote L2→L3 if consistent, demote L3→L2 if errors, retire low-value loops)
- [ ] **EVAL-003**: Scale decision framework (when to add loops, hardware, upgrade LLM tier)

**Done when**: Agents operate 24/7 on defined task catalog, LLM routing minimizes cost, autonomy levels enforced, effectiveness measured weekly.

### CG: Content Generation via Gitea (added 2026-03-25)

| ID | Task | Depends | Status |
|----|------|---------|--------|
| CG-001 | Create `mlorentedev/content` repo in Gitea with directory structure | F1 (Vikunja) | [ ] |
| CG-002 | Configure Gitea bot account with OIDC + scoped repo access | ADR-016 | [ ] |
| CG-003 | Implement Lorca agent (YouTube script drafts from vault context) | CLAW-003, CG-001 | [ ] |
| CG-004 | n8n workflow: Vikunja `content:draft` → OpenClaw → Gitea PR | N8N-003, CG-001 | [ ] |
| CG-005 | Implement Bécquer agent (newsletter polish from vault lessons) | CG-003 | [ ] |
| CG-006 | n8n workflow: Gitea merge → publish trigger (Beehiiv/mlorente.dev) | CG-004 | [ ] |

## Notes

- Absorbs kubelab `todo.md` Stream F (F1-F4) and Stream H (H2-H4)
- H1 (LLM routing) → [kubelab-gateway](kubelab-gateway.md) (absorbed by ADR-029, integrated into kubelab API)
- F5 (Agent memory) → [kubelab-memory](kubelab-memory.md) (absorbed by ADR-029, replaced by pgvector RAG)
- Security: agents NEVER get access to SOPS keys, prod credentials, or infra repos unless explicitly allowed
- Agent containers have no access to prod environments
- Agent writes ONLY to `80_inbox/` — human reviews and promotes content to correct vault zones
