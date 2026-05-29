---
id: "kubelab-runbook-debugging"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Debugging

## Overview

Diagnose and troubleshoot issues with KubeLab containers, inter-container connectivity, and local DNS resolution.

## Prerequisites

- Docker running with KubeLab containers active
- Access to the host where containers are deployed
- `curl`, `wget`, `nslookup` available

## Steps

### 1. View logs of a specific service (preferred: toolkit)

```bash
# View logs with toolkit (preferred method)
toolkit services logs api
toolkit services logs web
toolkit services logs traefik

# View logs without following
toolkit services logs api --no-follow
```

### 2. View logs with raw Docker (fallback)

```bash
# API logs
docker logs $(docker ps -q -f name=api) -f

# Traefik logs
docker logs $(docker ps -q -f name=traefik) -f

# Logs with timestamp
docker logs $(docker ps -q -f name=web) -f -t
```

### 3. Enter container for debugging

```bash
# Enter API
docker exec -it $(docker ps -q -f name=api) sh

# Enter web container
docker exec -it $(docker ps -q -f name=web) sh

# Execute specific command
docker exec $(docker ps -q -f name=api) ps aux
```

### 4. Verify connectivity between containers

```bash
# From web to API
docker exec $(docker ps -q -f name=web) wget -qO- http://api:8080/health

# From API to blog
docker exec $(docker ps -q -f name=api) curl -I http://blog:80
```

### 5. Local DNS problems

Development uses `mlorente.test` for the main site and `*.kubelab.test` for services.

```bash
# Verify DNS resolution
nslookup mlorente.test
nslookup api.kubelab.test
nslookup traefik.kubelab.test

# Test direct connectivity
curl -H "Host: mlorente.test" http://localhost
curl -H "Host: api.kubelab.test" http://localhost

# Check /etc/hosts entries are present
grep -E '(mlorente\.test|kubelab\.test)' /etc/hosts

# If DNS entries are missing, add them
make setup-local-dns

# Clear DNS cache (if using systemd-resolved)
sudo systemd-resolve --flush-caches
# macOS: sudo dscacheutil -flushcache
```

### 6. Staging DNS problems

Staging uses `*.staging.kubelab.live` and is accessed via WireGuard.

```bash
# Verify staging DNS (requires WireGuard connection)
nslookup mlorente.staging.kubelab.live
curl -f https://mlorente.staging.kubelab.live
```

## Verification

After applying a fix, verify the affected service responds:

```bash
# Local development
curl -f https://mlorente.test
curl -f https://api.kubelab.test/health

# Production
curl -f https://mlorente.dev
curl -f https://api.kubelab.live/health
curl -f https://blog.kubelab.live
```

## Rollback

If debugging leads to a broken state, restart the affected service:

```bash
# Preferred: toolkit
toolkit services down <service_name>
toolkit services up <service_name>

# Fallback: raw Docker
docker restart $(docker ps -q -f name=<container_name>)
```

Or perform a full environment rebuild per [local-development](local-development.md).

## Last tested

2026-02-08
