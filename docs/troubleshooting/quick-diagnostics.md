---
id: "kubelab-troubleshooting-quick-diagnostics"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Quick Diagnostics

Fast triage commands for KubeLab platform issues across development, staging, and production environments.

## Overall System Health

```bash
# Check overall status
make status

# Check all logs
make logs

# Environment validation
make env-validate

# Docker health check
docker ps -a
docker system df
```

## Service-Specific Checks

```bash
# Check specific app/service
toolkit apps logs api
toolkit services logs grafana
```

## Configuration Validation

```bash
# Validate configuration
ENVIRONMENT=dev toolkit config generate
docker compose -f infra/compose/apps/api/docker-compose.dev.yml config
```

## Network Inspection

```bash
# Network overview
docker network ls
docker network inspect mlorente-network
```

## Resource Usage

```bash
# Resource monitoring
docker stats --no-stream
df -h
free -h
```

## Self-Service Checklist

When encountering any issue, follow this order:

1. Check logs first: `toolkit apps logs <app-name> -f`
2. Validate environment: `make env-validate`
3. Verify configurations: `docker compose config`
4. Search existing issues: GitHub Issues, discussions
5. Review recent changes: `git log --oneline -10`
6. Check documentation in the vault: [service-catalog](../architecture/service-catalog.md), Runbooks

## Gathering Debug Information

When an issue requires deeper investigation, collect:

```bash
# Collect system info
uname -a
docker version
docker compose version

# Export environment (sanitize secrets!)
env | grep -E "API_|WEB_|TRAEFIK_" | sed 's/PASSWORD=.*/PASSWORD=***/'

# Capture logs
toolkit apps logs api --no-follow > api-logs.txt
toolkit services logs grafana --no-follow > grafana-logs.txt

# Docker diagnostics
docker ps -a > containers.txt
docker network ls > networks.txt
docker volume ls > volumes.txt
docker system df > disk-usage.txt

# Configuration dump
docker compose -f infra/compose/apps/api/docker-compose.dev.yml config > api-config.yml
```

## Reporting Issues

When opening an issue, include:

1. Environment: dev/staging/prod
2. Affected service: api, web, traefik, etc.
3. Expected behavior: What should happen
4. Actual behavior: What actually happens
5. Reproduction steps: How to reproduce
6. Logs: Relevant error messages
7. Configuration: Sanitized env vars, compose snippet
8. Timeline: When did it start? After what change?
