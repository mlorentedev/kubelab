---
id: "adr-064-agentic-observability-and-auto-triage"
type: adr
status: accepted
created: "2026-08-23"
tags: [architecture, observability, sre, loki, grafana, slack, n8n, agents]
related:
  - adr-009-prometheus-metrics-stack
  - adr-032-observability-stack-execution
  - adr-044-unified-notification-routing-fabric
  - adr-050-cross-context-command-center
owner: manu
---

# ADR-064: Agentic Observability & Automated SRE Triage Architecture

## Status

Accepted — 2026-08-23. Establishes the standard for human and AI-agent observability tooling, bidirectional Slack incident collaboration, and reactive n8n auto-triage.

## Context

### The Observability Gap for Autonomous and Interactive Agents

As KubeLab evolved into a multi-cluster, multi-node hybrid platform (Hetzner VPS prod, Bare-metal homelab staging/dev, GCP Spot VM GitOps hub), the observability surface grew significantly:
- **Logs:** Ingested into Loki via Vector DaemonSets and Traefik access logs.
- **Alerts:** Evaluated by Grafana Alertmanager across 12 SLO, SRE, quota, and certificate rules.
- **Notifications:** Routed via Apprise to n8n and distributed to Slack channels (`#alerts`, `#ops`, `#deployments`).
- **Cluster Events:** Emitted by Kubernetes kubelets, controllers, and node watchers.

However, a fundamental operational gap remained:
1. **Interactive Agents Were Blind to Telemetry:** When an engineer works with an AI coding assistant (Antigravity, Claude Code, etc.) on a bug or deployment, the agent could not query live Loki logs, check firing Grafana alerts, or read incident threads in Slack without manual copy-pasting by the human.
2. **Alerts Required Manual Human Triaging:** When Grafana fired a critical alert, n8n sent a notification to Slack, but investigating root cause still required a human operator to log into Grafana/Lens/k9s, parse raw logs, run `kubectl describe`, and consult the corresponding runbook.
3. **Context Window Token Exhaustion:** Direct raw log dumps easily exhaust LLM context windows with duplicated tracebacks and irrelevant debug noise.

## Decision

We establish the **Agentic Observability & Automated SRE Triage Architecture**, structured into two complementary operational planes:

```
+-----------------------------------------------------------------------------+
|                          KubeLab Observability Engine                       |
|   +-------------------+  +---------------------+  +---------------------+   |
|   |     Loki API      |  |  Grafana Alerting   |  |   Kubernetes API    |   |
|   |  (LogQL Streams)  |  |    (Alertmanager)   |  |  (Events / Pods)    |   |
|   +---------+---------+  +----------+----------+  +----------+----------+   |
+-------------|-----------------------|------------------------|--------------+
              |                       |                        |
              v                       v                        v
+-----------------------------------------------------------------------------+
|                     Unified SRE Layer: `toolkit obs`                        |
|   - logs: LogQL querying, timestamp slicing, traceback deduplication        |
|   - alerts: Live firing/pending rules table, silences, runbook resolution   |
|   - k8s: Warning events, unhealthy pod inspection, PVC capacity             |
|   - slack: Channel history, thread reading, triage response posting         |
|   - triage: Automated 4-step root cause diagnostic playbook                 |
+-------------------------------------+---------------------------------------+
                                      |
         +----------------------------+----------------------------+
         |                                                         |
         v                                                         v
+-----------------------------+               +-------------------------------+
|    1. Pull Mode (Query)     |               |    2. Push Mode (Reactive)    |
| - Interactive developer     |               | - Grafana -> Apprise -> n8n   |
|   assistant sessions        |               | - n8n triggers auto-triage    |
| - On-demand MCP tool calls  |               | - Agent analyzes Loki + K8s   |
| - Slack channel inspection  |               | - Posts diagnosis to Slack    |
+-----------------------------+               +-------------------------------+
```

### 1. Unified SRE Tooling: `toolkit obs`
All observability access is codified in `toolkit/features/observability.py` and exposed via the `toolkit obs` CLI namespace and MCP tools:
- **`toolkit obs logs`**: Executes LogQL queries against Loki with strict time bounds (`--since 15m`), service labels (`--service authelia`), log levels (`--level error`), and automatic deduplication of tracebacks.
- **`toolkit obs alerts`**: Queries Grafana Alertmanager for active alerts, annotations, and runbook links.
- **`toolkit obs k8s`**: Slices `Warning` events and unhealthy pod states without running raw kubectl scripts.
- **`toolkit obs slack`**: Connects via Slack Bot API to read recent channel alerts and thread conversations.
- **`toolkit obs triage`**: Executes the complete diagnostic playbook for a service or alert.

### 2. The 4-Step Automated Diagnostic Playbook
When an incident is triaged (interactively or reactively):
1. **Telemetry Slicing:** Fetch the last 5 minutes of Loki error logs for the target service.
2. **K8s Event Correlation:** Query Kubernetes API for `Warning` events (OOMKilled, Evicted, BackOff, CrashLoop).
3. **Runbook Mapping:** Match the alert UID / error signature with `docs/runbooks/runbook-*.md`.
4. **Structured Synthesis:** Produce a concise, actionable report:
   - **Root Cause** (exact failure mechanism).
   - **Blast Radius & Impact** (affected endpoints and HTTP error codes).
   - **Remediation Action** (executable command or config fix).

### 3. Reactive Event-Driven Triage via n8n
- On critical alerts, n8n publishes the alert card to Slack `#alerts` and records `ts` (thread timestamp).
- n8n triggers the automated triage worker via HTTP webhook.
- The worker executes `toolkit obs triage`, formats the markdown report, and posts it as an immediate reply in the Slack alert thread.

## Consequences

### Positive
- **Instant MTTD & MTTR:** Incidents are diagnosed with root causes identified in Slack within seconds of firing.
- **Token Efficiency:** Structured LogQL filters and deduplication prevent agent context saturation.
- **Zero Drift:** Humans, autonomous bots, and interactive agents use the exact same CLI and MCP tooling.
- **Safe & Auditable:** Read-only access by default; silences and remediations require explicit confirmation.

### Negative / Trade-offs
- **Network Dependency:** Requires Tailscale mesh or cluster-internal routing to reach Loki API (`:3100`) and Grafana API.
- **Slack Token Storage:** Requires Slack Bot Token in SOPS (`common.enc.yaml`) with `channels:history`, `channels:read`, and `chat:write` scopes.
