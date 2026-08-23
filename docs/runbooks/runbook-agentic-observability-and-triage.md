---
id: runbook-agentic-observability-and-triage
type: runbook
status: active
tags: [runbook, kubelab, observability, sre, triage, loki, grafana, slack, n8n]
created: "2026-08-23"
last_tested: "2026-08-23"
owner: manu
---

# Agentic Observability & SRE Incident Auto-Triage Runbook

> Operational manual for querying telemetry, interacting with Slack incident channels, and configuring reactive n8n automated triaging (ADR-064).

---

## 1. Quick Reference & CLI Commands

The `toolkit obs` command group provides direct access to cluster telemetry, alerting state, and Slack channels for both engineers and AI agents.

### A. Querying Logs (`toolkit obs logs`)
```bash
# Query error logs for a specific service in the last 15 minutes
poetry run toolkit obs logs --service authelia --since 15m --level error

# Query Traefik ingress logs with custom LogQL filter
poetry run toolkit obs logs --query '{container="traefik"} |~ "50[0-9]"' --since 30m

# Tail logs live (streaming)
poetry run toolkit obs logs --service api --follow
```

### B. Checking Active Alerts (`toolkit obs alerts`)
```bash
# List all currently firing and pending Grafana alerts
poetry run toolkit obs alerts list

# Create a temporary silence for planned maintenance
poetry run toolkit obs alerts silence --uid obs015-pvc-unbound-failure --duration 2h --reason "Disk migration"
```

### C. Kubernetes SRE Event Slicing (`toolkit obs k8s`)
```bash
# Extract recent Warning events across all namespaces
poetry run toolkit obs k8s events --since 30m

# List degraded/unhealthy pods and restart counts
poetry run toolkit obs k8s pods --unhealthy

# Check PVC binding state and storage capacity
poetry run toolkit obs k8s pvc
```

### D. Reading and Replying to Slack (`toolkit obs slack`)
```bash
# Read the last 5 messages from #alerts or #ops
poetry run toolkit obs slack read --channel alerts --limit 5

# Read an incident thread by timestamp
poetry run toolkit obs slack thread --channel alerts --ts 1724395000.123456

# Post a triage response into an incident thread
poetry run toolkit obs slack post --channel alerts --thread 1724395000.123456 --message "Root cause identified: OOMKilled"
```

---

## 2. Automated SRE Triage Workflow

When an alert fires or when manually invoked, the triage engine executes a structured 4-step diagnostic sequence:

```bash
poetry run toolkit obs triage --service <service_name>
# or
poetry run toolkit obs triage --alert <alert_uid>
```

### Diagnostic Sequence:
1. **Pod & Node Health Check:** Calls Kubernetes API for the target workload. Identifies container crash codes (e.g., `137` = OOMKilled, `1` = Application Exception), restarts, and resource saturation.
2. **Telemetry Log Slicing:** Extracts Loki logs from `T_alert - 5m` to `T_alert + 2m`. Deduplicates stack traces and highlights the initial failure line.
3. **Runbook & Knowledge Correlation:** Resolves the `runbook_url` annotation in the alert rule (or maps the service to `docs/runbooks/runbook-*.md`).
4. **Structured Incident Synthesis:** Emits a formatted incident report.

---

## 3. n8n Reactive Webhook Integration

The n8n notification router (`notify-router.json`) integrates with the auto-triage engine on critical alerts:

1. **Trigger:** Alertmanager posts to `https://n8n.<env>.kubelab.live/webhook/notify`.
2. **Channel Dispatch:** n8n routes the alert to Slack `#alerts` and captures the resulting message `ts`.
3. **Triage Hook:** n8n sends an HTTP POST to the triage dispatcher:
   ```json
   {
     "alert_uid": "obs015-slo-fast-burn-rate",
     "service": "api",
     "namespace": "kubelab",
     "channel": "alerts",
     "thread_ts": "1724395000.123456"
   }
   ```
4. **Thread Reply:** The triage worker posts the synthesized root cause report directly into the Slack thread.

---

## 4. Troubleshooting Telemetry Connectivity

| Symptom | Cause | Resolution |
|---|---|---|
| `Connection refused: Loki API` | Tailscale mesh unreachable or Loki pod not running | Check `kubectl get pods -n kubelab -l app.kubernetes.io/name=loki` and verify Headscale VPN (`100.64.0.2:3100`). |
| `Slack API error: not_in_channel` | Slack bot not invited to the channel | Run `/invite @KubeLabBot` in `#alerts` and `#ops`. |
| `Grafana Alertmanager 401 Unauthorized` | Missing or expired basic auth / service account token | Verify `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in `grafana-admin` secret via SOPS. |
