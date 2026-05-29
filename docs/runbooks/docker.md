---
id: "kubelab-runbook-docker"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-08"
owner: manu
---

# Docker

## Overview

Manage Docker resources for KubeLab: build images, clean up unused images/volumes, inspect resource usage, perform multi-architecture builds, and verify container health checks.

## Prerequisites

- Docker and Docker Buildx installed
- Access to the host running KubeLab containers
- Docker Hub credentials (for pushing multi-arch images)

## Steps

### 1. Build images (preferred: toolkit)

```bash
# Build specific app with toolkit (preferred method)
toolkit services build web
toolkit services build api
toolkit services build blog

# Build with no cache
toolkit services build web --no-cache
```

### 2. Clean Docker system

```bash
# Clean unused images
docker system prune -f

# Clean everything (images, volumes, networks)
docker system prune -af --volumes

# Clean only dangling images
docker image prune -f

# Full clean via Makefile
make dev-full-clean
```

### 3. Inspect Docker resources

```bash
# View resource usage
docker stats --no-stream

# View images by size
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | sort -k3 -h

# View volumes
docker volume ls
```

### 4. Multi-arch builds

```bash
# Create multi-arch builder
docker buildx create --use --name multiarch

# Build for both architectures
docker buildx build --platform linux/amd64,linux/arm64 -t test:latest .

# Push multi-arch
docker buildx build --platform linux/amd64,linux/arm64 -t user/image:tag --push .
```

### 5. Verify health checks

```bash
# View health check status
docker ps --format "table {{.Names}}\t{{.Status}}"

# Inspect health check of a container
docker inspect $(docker ps -q -f name=web) | jq '.[].State.Health'
```

## Verification

```bash
# Confirm containers are running and healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# Confirm disk usage is acceptable
docker system df
```

## Rollback

If a prune removed needed images, rebuild them:

```bash
# Preferred: toolkit
toolkit services build web
toolkit services build api
toolkit services build blog
toolkit services up web api blog

# Fallback: raw Docker compose
docker compose -f infra/stacks/apps/web/compose.base.yml \
  -f infra/stacks/apps/web/compose.dev.yml up -d --build
```

If a multi-arch builder is broken, remove and recreate:

```bash
docker buildx rm multiarch
docker buildx create --use --name multiarch
```

## Last tested

2026-02-08
