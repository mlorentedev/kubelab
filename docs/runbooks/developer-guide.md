---
id: "kubelab-dev-guide"
type: runbook
status: active
created: "2026-02-22"
owner: manu
---

# KubeLab Developer Guide

## Best Practices Reference

### Compose File Pattern

```bash
docker compose -f compose.base.yml -f compose.dev.yml up -d

# compose.base.yml: image, healthcheck, networks, volumes
# compose.dev.yml: hot reload, debug, local ports
# compose.staging.yml: mirrors prod, limited resources
# compose.prod.yml: resource limits, logging, replicas
```

### Service Categories

| Category | Purpose | Services |
|----------|---------|----------|
| **core** | Essential platform | gitea, portainer, n8n, vaultwarden, vikunja |
| **observability** | Monitoring/logging | grafana, loki, uptime, prometheus |
| **security** | Auth/protection | authelia, crowdsec |
| **data** | Storage | minio |
| **automation** | CI/workflows | github-runner |
| **ai** | ML/AI agents | openclaw, picoclaw, pollex |
| **misc** | Productivity | calcom, immich |

### Environment Strategy

```
dev      → Local (hot reload, debug, mkcert certs)
staging  → Acemagic homelab (mirrors prod, Tailscale access)
prod     → Hetzner VPS (public, Let's Encrypt TLS)
```

### CLI Command Reference

```bash
kubelab services up <name>       # Start app or service
kubelab services down <name>     # Stop
kubelab services logs <name>     # View logs
kubelab services list            # List available
kubelab config generate          # Generate configs from templates
kubelab config validate          # Validate configs
kubelab credentials generate     # Generate credentials
kubelab infra ansible deploy     # Deploy with Ansible
kubelab infra terraform plan     # Terraform plan
kubelab deployment deploy        # Full deployment pipeline
kubelab dashboard                # Terminal dashboard
kubelab monitoring backup         # Pull Uptime Kuma DB
kubelab monitoring restore        # Push DB to RPi3
kubelab monitoring status         # Check Uptime Kuma health
kubelab tools certs generate     # Generate local certs
kubelab docs serve               # Serve project documentation
```
