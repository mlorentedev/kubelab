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
Verifies authenticated delivery and that the webhook refuses both a missing and a wrong secret:
```bash
make notify-smoke ENV=staging
```
Four probes against `https://n8n.staging.kubelab.live/webhook/notify`: `page` and `log` with the
SOPS secret expect 200, and a POST with no `Authorization` header and one with a wrong `Bearer`
value expect 403. The wrong value is random per run and never printed. A 200 says n8n routed the
envelope and Apprise accepted it; confirm the messages landed in `#alerts` and `#ops-log`, because
nothing reads the channels back.

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

---

## 6. SRE Smart Evaluation, Inhibit Rules & Dead Man's Switch (OBS-015)

To prevent alert storms, cascading noise, and false-quiet outages, Grafana Alertmanager is provisioned with deterministic inhibit rules and watchdog monitoring:

### A. Inhibit Rules Hierarchy (`inhibit-rules.yaml`)
1. **Severity Escalation Suppression**: When `severity: critical` fires for an alert, duplicate `warning` or `info` notifications for the same alertname and namespace are suppressed.
2. **Infrastructure Outage Suppression**: When a host/node failure alert fires (`NodeNotReady`, `KubeNodeNotReady`, `InstanceDown`), downstream container/pod restart alerts (`PodCrashLooping`, `ServiceDown`) on that instance are inhibited.
3. **Edge Ingress Outage Suppression**: When edge ingress fails (`TraefikDown`), cascading HTTP 5xx rate alerts are suppressed.
4. **Backup Job Failure vs Freshness**: Explicit backup job failures inhibit secondary freshness staleness warnings for the same bucket.

### B. Dead Man's Switch Watchdog (`obs015-deadmansswitch-heartbeat`)
- Continuous watchdog heartbeat rule evaluating Loki/Vector pipeline ingestion.
- Configured with threshold `lt 1` and `noDataState: Alerting` / `execErrState: Alerting`: if Loki log ingestion ceases or returns no data during evaluation, an alert is triggered. External endpoint health checks (e.g. Uptime Kuma) cover whole-evaluator outages.

### C. TLS Certificate Early Warning (`obs015-tls-early-warning`)
- Evaluates Traefik ingress logs for repeated ACME certificate renewal failures with `for: 5m`, generating actionable alert links before certificates expire.

## 7. Symptom-Based Multi-Window Multi-Burn-Rate SLOs (`slo-rules.yaml`)

Following Google SRE error budget doctrine, public ingress alerts fire on actual user-visible symptom degradation rather than single-instant error spikes:
- **Fast Burn Rate (`obs015-slo-fast-burn-rate`)**: 14.4x normal error rate capacity in a 1-hour window (evaluating >50 HTTP 5xx errors from Traefik ingress logs, `for: 2m`). Consumes ~2% of the 30-day budget in 1 hour; triggers an immediate page in prod.
- **Medium Burn Rate (`obs015-slo-medium-burn-rate`)**: 6x normal error rate capacity in a 6-hour window (evaluating >100 HTTP 5xx errors from Traefik ingress logs, `for: 15m`). Consumes ~5% of the 30-day budget in 6 hours; triggers a warning in ops logs.

## 8. Fleet Volume & Disk Saturation Watcher (`disk-watcher.yaml` & `disk-rules.yaml`)

- In-cluster CronJob `disk-watcher` runs every 15 minutes inspecting PVCs and root disk capacity in `kubelab`.
- Evaluates PVC Bound phase (`obs015-pvc-unbound-failure`) with `noDataState: Alerting`.
- Alerts if root filesystem capacity crosses 90% (`obs015-disk-root-saturation`).

## 9. Perimeter Threat Defense (`security-rules.yaml`)

- Evaluates CrowdSec container decision and bouncer logs (`obs015-crowdsec-ban-surge`).
- Alerts when more than 5 automated IP ban decisions occur in a 10-minute window.

## 10. Forge Reviewer Failure (TOOL-093)

PR-Agent, the forge's reviewer, logs `Failed to review PR` when every configured model fails, and then publishes nothing on the pull request. From the PR that looks like a webhook that never arrived, so the rule `tool093-reviewer-failed` in `rules.yaml` (group `forge-review`) reads that line from Loki (`{container="pr-agent"}`) and alerts once per pull request.

- **What to do:** push a commit to the pull request. A `/review` comment is ignored by the forge reviewer (#1963), so a push is the only retry.
- **Failed review or lost webhook:** every PR-Agent line for a delivery carries the PR's URL. `toolkit obs logs --env prod --service pr-agent --since 1h --query '{container="pr-agent"} |= "<PR URL>"'` finds lines for that PR if the webhook arrived (a `Failed to review PR` among them means this alert's case) and finds none if it never did, which is a Gitea webhook delivery problem instead.
- **Why it happened:** `toolkit obs logs --env prod --service pr-agent --since 1h` shows each model's error (an authentication refusal, a timeout, an exhausted quota). The same cause on every PR is a provider problem, not the PR.
- **`finish_reason: length`:** the commonest cause so far. The log reads `Streaming response resulted in empty content but completed with finish_reason: length`, followed by `Unknown error during LLM inference: APIError.__init__() missing 1 required positional argument: 'request'`. The second line is PR-Agent 0.45.0 failing to build its own error, not a second fault: the model spent its budget on reasoning and wrote no review. There are two limits behind it (lesson-601). deepseek-v4-flash is cut at 32768 completion tokens unless the request names more, so the reviewer sends `CONFIG__MAX_OUTPUT_TOKENS` (`pr-agent.env`). mimo-v2.6-flash is cut by the clock, at about 600 s with the budget unspent, and no setting moves that: tell them apart by the elapsed time between `Generating prediction` and the `length` line (near 600 s is mimo). Each model is tried twice before the next one, so `Failed to review PR` can arrive up to an hour after the push (two attempts of about 600 s on each of three models).
- **Which model reviews first:** the forge server tries its models in the order of `pr_agent.forge_rank` in `harness/reviewer-pool.json` (deepseek, glm, mimo), not by the CI weight, which would put mimo first. The key exists in kubelab's copy only (owner, 2026-10-18); `tests/test_pr_agent_config_render.py` fails if the env and the ranks disagree.
- **Silence is health:** no failure lines means no series, and the rule maps that to OK. A reviewer that is down entirely is caught by the `review-attestation` gate, not by this rule.
- **The PR author is told too:** the same alert goes to a second contact point, `forge-review-failed`, which POSTs Grafana's stock webhook body to `http://n8n:5678/webhook/forge-review-failed` with `Authorization: Bearer $N8N_WEBHOOK_SECRET` (the n8n webhook secret, delivered to the Grafana pod through `grafana-admin`; `make apply-secrets` after rotating it). An n8n workflow then comments on the PR with its own comment-only Gitea token (`gitea-review-notice`, see `gitea-credential-recovery.md`). A `403` in Grafana's notifier log for this receiver is the bearer disagreeing with n8n's credential, not a workflow bug; a `404` means the workflow is not imported (`make import-n8n ENV=prod`). The pod's reference to the secret is `optional`, so Grafana starts before `apply-secrets` has written the key; until then the bearer is empty and every call is refused with that `403`, and the page still goes out.
- **What the workflow does, and how to read its runs:** it posts one comment per alert episode, recognised by a marker (`<!-- forge-review-failed:<startsAt> -->`) in a comment on the PR, so a group Grafana re-sends does not comment twice and a new episode of the same PR (a new `startsAt`) does. A second failure inside the 15 minutes of the first one is the same episode and gets no second notice. A repeat, a resolved alert and a label that is not a pull request of this forge all end in the `Nothing To Post` node and answer `200`. Gitea refusing the read or the post (a dead `gitea-review-notice` token, a deleted PR, a locked conversation) ends the run in an error and answers `500`, on purpose: no HTTP node swallows errors (`tests/test_n8n_forge_review_failed.py`), so the notice is not lost behind a `200`, and Grafana sends the group again on its next flush for as long as the alert fires (15 minutes). One refused PR therefore holds back the PRs after it in the same group until that window ends; this is accepted, the cost of isolating each item being a silent `200` for a notice that was never posted. The allowlist is host-level: any `owner/repo` of the forge is accepted, since the label comes from the reviewer's own log line and the comment is fixed text. The execution record in n8n keeps the inbound `Authorization` header of the webhook (as for every webhook workflow here) and not the Gitea token.
- **Re-running the workflow against the pinned runtime:** the Code-node tests run in Node, which has globals the task runner's sandbox lacks (lesson 600), so after changing the n8n pin or the workflow run it once for real: start `n8nio/n8n:<pin>` and a `gitea/gitea:<pin>` with a PR on one Docker network, replace `https://RESOLVE_GITEA_DOMAIN` in a copy of the workflow with that Gitea's URL, `n8n import:credentials` (a Header Auth `forge-review-failed-webhook` and `gitea-review-notice` with a `write:issue` token) and `n8n import:workflow`, `n8n publish:workflow --id=d6000000-0000-4000-8000-000000000001`, restart, then POST `tests/fixtures/grafana/forge-review-failed-webhook.json`'s `body` to `/webhook/forge-review-failed` with the bearer. Expect `200` and one comment on the PR; the same POST again, `200` and none; a wrong bearer, `403`; read an execution's error in `execution_data` of `~/.n8n/database.sqlite`.
- **Adding a route under the root policy:** an alert that matches a child route no longer reaches the root's own receiver, and `continue: true` does not change that, it only lets the walk go on to the next sibling. The policy therefore repeats the tier's receiver as the first child for this alert (measured on grafana-oss 13.0.2, 2026-10-18: with only the new route, n8n was notified and the page was not). `tests/test_forge_review_failed_route.py` walks the rendered tree and fails if either receiver goes missing.
