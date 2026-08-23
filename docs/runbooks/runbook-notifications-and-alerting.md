---
id: runbook-notifications-and-alerting
type: runbook
status: active
tags: [runbook, kubelab, notifications, alerting, slack, n8n, apprise, sre]
created: "2026-08-22"
last_tested: "2026-08-22"
owner: manu
---

# Unified Notification & Alert Routing Fabric (Slack Multi-Channel)

> Operational guide for managing, testing, and troubleshooting the central notification fabric (ADR-044 / NOTIFY-002).

---

## 1. Architecture Overview

All notification emitters across the infrastructure (Kubernetes, Bare Metal fleet nodes, Cloud providers, and the Knowledge Vault) route through a single entry point:

```text
┌─────────────────────────────────────────────────────────────┐
│                      EMITTERS (Sources)                     │
│                                                             │
│  - Knowledge Vault (vault-validate.py)                      │
│  - Ansible Fleet (kubelab-notify@.service on systemd fail)  │
│  - Argo CD & GitOps (deployments/syncs)                     │
│  - Grafana Alertmanager & Uptime Kuma (metrics & outages)   │
│  - Hermes & AI Agents (crons, market briefings)             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
        POST https://n8n.<env>.kubelab.live/webhook/notify
        (Header: "Authorization: Bearer <webhook_secret>")
                               │
                               ▼
            ┌────────────────────────────────────┐
            │   n8n Router (notify-router.json)  │
            │   Maps domain + severity -> Tag    │
            └──────────────────┬─────────────────┘
                               │
                               ▼
            ┌────────────────────────────────────┐
            │   Apprise Service (stateless)      │
            │   Reads kubelab.yml from SOPS      │
            └──────────────────┬─────────────────┘
                               │
       ┌───────────┬───────────┼───────────┬───────────┐
       ▼           ▼           ▼           ▼           ▼
   🚨 #alerts  🧠 #vault  🚀 #deploy  📋 #ops-log 🤖 #agent
```

---

## 2. Channel Taxonomy & Tag Mapping

| Apprise Tag | Slack Channel | Primary Use & Trigger | Severity / Emoji |
| :--- | :--- | :--- | :--- |
| **`page`** | `#alerts` | Critical incidents: Uptime Kuma down, Grafana alert firing, node systemd failure. | 🚨 `page` / `failure` |
| **`vault`** | `#vault-health` | Knowledge Vault governance: weekly health check, Dependabot-style issues. | 🧠 `info` / `vault` |
| **`deploy`** | `#deployments` | GitOps & Delivery: Argo CD syncs, Docker image releases. | 🚀 `notice` / `deploy` |
| **`log`** | `#ops-log` | Background ops & Maintenance: R2 backups (`restic`), disk cleanup, routine logs. | 📋 `log` / `info` |
| **`agent`** | `#agent-fleet` | AI Fleets: Hermes daily briefing, OpenClaw task delegations. | 🤖 `info` / `agent` |

---

## 3. Payload Contract

Emitters send a JSON payload with the following contract:

```json
{
  "domain": "ops|vault|deploy|agent",
  "severity": "page|notice|log|info",
  "title": "[STAGING] Uptime Kuma: API Down",
  "body": "HTTP 503 from https://api.kubelab.live (probe timeout 5s)",
  "source": "k8s/uptime-kuma"
}
```

---

## 4. Operational Testing Procedures

### A. End-to-End Smoke Test (`notify-smoke`)
Verifies authenticated delivery and unauthenticated rejection:
```bash
make notify-smoke ENV=staging
```

### B. In-Cluster Grafana Contact Point Probe
Simulates a live alert from Grafana to Apprise:
```bash
kubectl --kubeconfig ~/.kube/kubelab-staging-config exec -n kubelab deploy/grafana -- \
  wget -qO- --post-data='{"tag":"page","title":"[STAGING] Grafana Alert Probe","body":"Testing Grafana -> Apprise -> Slack","type":"failure"}' \
  --header='Content-Type: application/json' http://apprise:8000/notify/kubelab
```

### C. Ansible Fleet Systemd Failure Probe
Tests `kubelab-notify@.service` execution on a fleet node:
```bash
make maintain-notify-test NODE=vps ENV=staging
```

### D. Knowledge Vault Validation Run
Tests health scan and notification dispatch:
```bash
python3 "$VAULT_PATH/00_meta/scripts/vault-validate.py" --json --strict
```

---

## 5. Adding or Rotating Slack Webhooks

1. Generate the Incoming Webhook in the **KubeLab** Slack App (https://api.slack.com/apps).
2. Edit encrypted secrets in SOPS:
   ```bash
   make secrets ENV=staging   # and/or ENV=prod
   ```
3. Update the `apps.services.automation.apprise.slack` block:
   ```yaml
   apps:
     services:
       automation:
         apprise:
           slack:
             webhook_alerts: "https://hooks.slack.com/services/..."
             webhook_vault: "https://hooks.slack.com/services/..."
             webhook_deployments: "https://hooks.slack.com/services/..."
             webhook_log: "https://hooks.slack.com/services/..."
             webhook_agent: "https://hooks.slack.com/services/..."
   ```
4. Apply the updated secrets to K8s and restart Apprise:
   ```bash
   poetry run toolkit secrets apply --env staging
   kubectl --kubeconfig ~/.kube/kubelab-staging-config rollout restart deploy/apprise -n kubelab
   ```
