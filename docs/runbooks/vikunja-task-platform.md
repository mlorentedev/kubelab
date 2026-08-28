# Runbook: Self-Hosted Task Platform (Vikunja + n8n + Slack)

> **Audience**: Platform Operator / AI Agents  
> **Status**: Production  
> **Related Architecture**: [ADR-066](../adr/adr-066-self-hosted-task-platform.md), [ADR-050](../adr/adr-050-cross-context-command-center.md), [ADR-051](../adr/adr-051-postgres-data-service.md)

---

## 1. Overview & Architecture

Vikunja is KubeLab's self-hosted, forge-agnostic task management platform. It replaces GitHub Projects v2 with a lightweight (~50MB RAM), 100% stateless deployment that unifies tasks across public GitHub repositories and private Gitea repositories.

```mermaid
flowchart TD
    User([Operator / Slack / Web UI]) -->|Browser / SSO| Ingress[Traefik TLS Ingress\ntasks.kubelab.live]
    Slack[Slack Slash Command] -->|POST /webhook/slack-task-capture| n8n[n8n Automation Engine]
    Forges[GitHub / Gitea PR Events] -->|POST /webhook/multi-forge-sync| n8n
    
    Ingress -->|No ForwardAuth| Vikunja[Vikunja Pod\nStateless ~50MB RAM]
    n8n -->|REST API Bearer Token| Vikunja
    
    Vikunja -->|Relational Data| Postgres[(PostgreSQL 16\ninfra.postgres / DB: vikunja)]
    Vikunja -->|Attachments & Avatars| R2[(Cloudflare R2\nS3 Bucket: kubelab-vikunja)]
    
    n8n -->|Notifications| Apprise[Apprise\n#dev-activity]
```

---

## 2. Day-to-Day Operations

### Web Access & Authentication
- **Production URL**: `https://tasks.kubelab.live`
- **Staging URL**: `https://tasks.staging.kubelab.live`
- **Authentication**: Single Sign-On via Authelia OIDC. Click "Login with Authelia".

### Slack ChatOps Syntax
From any authorized Slack channel:
```text
/task create [title] #[project] [P0|P1|P2|P3]
```
**Examples**:
- `/task create Refactor auth layer #kubelab P1`
- `/task create Update CV experience #personal P2`
- `/task create Deploy firmware pipeline #teledyne P0`

Slack receives an acknowledgment within <500ms, and n8n asynchronously creates the task in Vikunja.

### Platform Reconciliation (Idempotent SSOT Sync)
To reconcile namespaces (`kubelab`, `personal`, `teledyne`), standard labels, and webhooks:
```bash
# Sync staging
make sync-vikunja ENV=staging

# Sync prod
make sync-vikunja ENV=prod
```
*Note: Running `make sync-vikunja` is strictly idempotent (`changed=0` on re-run).*

---

## 3. Multi-Forge Lifecycle Automation

Both GitHub and Gitea trigger webhooks into n8n when PRs are created, updated, or merged.

### Lifecycle Conventions
1. Branch name or PR title carries the task/spec key (e.g. `feat/idp-035-vikunja-task-platform` or `feat: IDP-035 add sync`).
2. **PR Opened / Synchronized**: n8n moves the corresponding Vikunja task to `In Review` and comments with the PR URL.
3. **PR Merged**: n8n moves the task to `Done` (terminal state; monotonic and ignores stale out-of-order events).

---

## 4. Autonomous Agent Delegation

To delegate a task to an autonomous coding agent (Orca ADE / CLI agent in an isolated worktree):
1. Attach the label `agent:delegable` to the task in Vikunja.
2. The `agent-dispatcher` n8n workflow emits a normalized execution payload containing:
   - Target repository and branch (`feat/<feature-id>-task`)
   - Spec ID and requirements
3. On-demand dev nodes (`ace2` / Beelink) pull pending tasks upon boot via `tk task sync`.

---

## 5. Troubleshooting & Health Probes

### Check Vikunja Pod Status
```bash
kubectl -n kubelab get pods -l app.kubernetes.io/name=vikunja
kubectl -n kubelab logs -l app.kubernetes.io/name=vikunja --tail=50
```

### Direct Health Check
```bash
curl -s -f https://tasks.kubelab.live/api/v1/info | jq .
```

### PostgreSQL Tenant Verification
```bash
# Check if vikunja database exists
kubectl -n kubelab exec -it deployment/postgres -- psql -U kubelab -d kubelab -c "\l"
```
