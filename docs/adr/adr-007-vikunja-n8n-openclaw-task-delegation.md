---
id: "kubelab-adr-007-vikunja-n8n-openclaw-task-delegation"
type: adr
status: superseded
superseded_by: adr-002-orchestrator-architecture
tags: [adr, kubelab]
created: "2026-02-12"
owner: manu
---

# ADR-007: Vikunja + n8n + OpenClaw for Agent-Delegated Task Management

## Status

Accepted (2026-02-12)

## Context

The project needs a self-hosted task management system that:

1. Replaces Google Keep for personal/work task management (quick capture, labels, states)
2. Supports delegating tasks to AI agents (OpenClaw) with human-in-the-loop validation
3. Communicates with AI agents via Slack for checkpoint approvals
4. Separates projects by domain (work, personal, KubeLab) with per-project AI delegation policies
5. Must be fully open source and self-hosted

The novel requirement is not the task manager itself, but the **agent delegation workflow**: tasks tagged as delegable are picked up by AI agents, decomposed into subtasks, executed with human checkpoints, and only completed after explicit human approval.

## Decision

### Architecture: Compose, don't build

Use three independent, replaceable components:

| Component | Role | Tech |
|-----------|------|------|
| **Vikunja** | Task manager (UI, labels, states, kanban, API) | Go + Vue, GPLv3 |
| **n8n** | Workflow orchestrator (webhooks, Slack, state machine) | Node.js, sustainable use license |
| **OpenClaw** | AI agent execution and isolation | Open source agent framework |

### Why Vikunja (over Plane, Taiga, Kanboard)

| Criterion | Vikunja | Plane | Taiga | Kanboard |
|-----------|---------|-------|-------|----------|
| RAM usage | **~50MB** | ~500MB | ~300MB | ~30MB |
| API REST | Good (OpenAPI) | Excellent | Good | JSON-RPC |
| Webhooks | Yes | Yes | Yes | Yes |
| Custom fields | No | Yes | Yes | Via plugins |
| Quick capture | **Todoist-like** | PM-heavy | PM-heavy | Partial |
| Deploy complexity | 1 container + DB | 5 containers | 4 containers | 1 container |
| Mobile | PWA + CalDAV | PWA | PWA | Responsive |

**Key trade-off**: Vikunja lacks custom fields. Agent context (repo, branch, checkpoints) is stored as a **structured YAML block in the task description**, parsed by n8n via API. This is a pragmatic workaround — the same pattern used in GitOps (structured data in free-text fields). If Vikunja adds custom fields in the future, migration is straightforward.

### Why n8n as orchestrator (not custom Python)

n8n already provides every capability the orchestrator needs:
- Webhook triggers (Vikunja events)
- HTTP Request nodes (OpenClaw API, Vikunja API)
- Wait nodes with callback (checkpoint approval)
- Slack nodes (native integration)
- Timeout handling
- Conditional logic (IF/Switch nodes)

Building a custom Python orchestrator service would duplicate n8n's capabilities and add maintenance burden. n8n is already planned for deployment in the KubeLab stack.

### Agent delegation level

**Level 2**: Agent receives a task, proposes a decomposition into subtasks, executes them sequentially, and pauses at human-configured checkpoints for approval. No multi-agent collaboration (Level 3) in v1.

### Agent context convention

Tasks delegable to agents include a YAML block in the description:

```yaml
# --- agent context ---
repo: kubelab
branch: feature/auth-refactor
checkpoints: per-subtask
constraints: "no tocar modulo billing"
```

n8n parses this block from the Vikunja API response to configure the OpenClaw agent.

## Workflow

```
1. User creates task in Vikunja with label `agent:delegable`
2. Vikunja webhook → n8n
3. n8n validates label, extracts agent context from description
4. n8n calls OpenClaw: "Decompose this task"
5. Agent proposes subtasks → n8n notifies via Slack
6. User approves decomposition (Slack button or Vikunja state change)
7. n8n launches subtask 1 via OpenClaw
8. Agent works, produces artifacts (PR, files, etc.)
9. At checkpoint: n8n pauses, notifies Slack with artifacts
10. User reviews → approve/reject
11. Loop until all subtasks complete
12. n8n marks parent task as Done in Vikunja
```

## Project separation

Vikunja projects with per-project AI delegation policy:

| Project | AI delegation | Example |
|---------|--------------|---------|
| `kubelab/infra` | Yes | Infrastructure tasks |
| `kubelab/apps` | Yes | App development |
| `trabajo/tareas` | No | Work tasks, manual only |
| `personal/casa` | No | Personal tasks |
| `personal/side-projects` | Yes | Side project development |

The delegation policy is enforced by convention: only tasks with label `agent:delegable` trigger the n8n pipeline. Projects without that label are pure task management.

## Explicit limits (v1)

| Limit | Reason |
|-------|--------|
| No auto-merge of PRs | Human always decides |
| No production access for agents | Agents only work in dev/staging |
| No inter-agent communication | Complexity explosion, not needed yet |
| No auto-advance at checkpoints | Always waits for human OK |
| 1 repo per task | Simplifies agent context |
| No cost controls (v1) | But token usage is tracked in audit log |
| Multi-repo agent access | User configures which repos agents can access |

## Anti-features (explicitly out of scope)

- Building a task manager from scratch
- Giving agents access to secrets/SOPS
- Agent-initiated production deployments
- Vague tasks without concrete definition ("make it better")

## Consequences

1. **Vikunja** added to `infra/stacks/services/core/vikunja/` — lightweight, serves both personal and agent-delegated tasks
2. **n8n** role expands from general automation to include agent orchestration workflows
3. **OpenClaw** added to `infra/stacks/services/ai/openclaw/` — agent execution environment
4. **Slack integration** via n8n nodes — no custom Slack bot needed
5. **No custom orchestrator service** — n8n handles all workflow logic
6. **YAML-in-description convention** must be documented and enforced by n8n validation

## Related

- [adr-003-hybrid-rpi-hetzner](adr-003-hybrid-rpi-hetzner.md) — Infrastructure where this runs
- [service-catalog](../architecture/service-catalog.md) — New services to register
- [deployment](../troubleshooting/deployment.md) — Deployment procedures for new services
