---
id: "kubelab-troubleshooting-docker-containers"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Docker & Container Issues

Problems related to Docker images, container lifecycle, resources, and volumes in KubeLab.

## Dev: `blog` crashes with `Permission denied` on `.jekyll-cache`

### Root Cause

If any `docker run` or `make` command starts the blog container as root (e.g., without `user:` override), Jekyll creates `.jekyll-cache/` inside the mounted source directory owned by root. Subsequent runs as UID 1000 can't write to those files.

### Solution

```bash
sudo rm -rf apps/blog/jekyll-site/.jekyll-cache/
```

### Prevention

`_config.dev.yml` sets `cache_dir: /tmp/.jekyll-cache` so Jekyll never writes cache to the host-mounted source directory. This was added 2026-02-24.

---

## Dev: `web` crashes with `EACCES` on `/app/node_modules/.astro/`

### Root Cause

The anonymous Docker volume for `/app/node_modules` was initialized with root ownership from a previous container run (e.g., `make build-dev` without the correct user). Docker does not reinitialize volumes on restart.

### Solution

```bash
docker rm -vf web
tk services build web --env dev
tk services up web --env dev
```

The `-v` flag removes the anonymous volume, forcing Docker to reinitialize it from the image (where node_modules are owned by UID 1000).

---

## Image Pull Errors

### Problem

Failed to pull images from Docker Hub or private registry.

### Diagnostic Steps

```bash
# Check Docker Hub status
curl -I https://hub.docker.com

# Verify authentication
docker login

# Check rate limits
curl -s -H "Authorization: Bearer $(cat ~/.docker/config.json | jq -r '.auths."https://index.docker.io/v1/".auth' | base64 -d)" \
  https://auth.docker.io/token?service=registry.docker.io\&scope=repository:ratelimitpreview/test:pull | jq

# Check registry usage in compose files
grep -r "registry" infra/compose/
```

### Solution

```bash
# Pull specific image manually
docker pull mlorente/api:latest

# Use mirror/proxy (if configured)
docker pull mirror.gcr.io/library/nginx:latest

# Build locally instead
toolkit apps build api
```

### Prevention

- Use authenticated Docker Hub pulls to avoid rate limits
- Consider a local registry mirror for frequently used images
- Pin image versions instead of using `latest`

## Container Crashes

### Problem

Containers restart continuously (CrashLoopBackOff equivalent).

### Diagnostic Steps

```bash
# Check container status
docker ps -a | grep Restarting

# View crash logs
docker logs --tail 100 crashed-container

# Inspect exit code
docker inspect crashed-container | grep -A 5 State

# Check resource limits
docker stats crashed-container
```

### Solution

```bash
# Increase memory limit in compose file
# resources:
#   limits:
#     memory: 512M

# Disable restart policy temporarily
docker update --restart=no crashed-container

# Debug with interactive shell
docker run -it --entrypoint /bin/sh image-name

# Check for missing environment variables
docker inspect crashed-container | grep -A 20 Env
```

### Prevention

- Set appropriate resource limits for each service
- Implement health checks that catch degraded states before crashes
- Log crash reasons to a persistent location

## Restart Loops

### Problem

Container starts then immediately exits, causing restart loop.

### Diagnostic Steps

```bash
# Check entrypoint/command
docker inspect looping-container | grep -A 5 Entrypoint
docker inspect looping-container | grep -A 5 Cmd

# View all container logs
docker logs looping-container --timestamps

# Check health check failures
docker inspect looping-container | grep -A 10 Health
```

### Solution

```bash
# Disable health check temporarily
# healthcheck:
#   test: ["CMD", "true"]

# Override entrypoint for debugging
docker run --entrypoint /bin/sh -it image-name

# Check file permissions
docker exec looping-container ls -la /app/

# Verify dependencies are available
docker exec looping-container netstat -an
```

### Prevention

- Test entrypoints locally before deploying
- Use `depends_on` with health check conditions in compose files
- Implement graceful startup with dependency waiting

## Resource Limits

### Problem

Out of memory (OOM) kills or CPU throttling.

### Diagnostic Steps

```bash
# Monitor resource usage
docker stats --no-stream

# Check host resources
free -h
top
df -h

# Identify resource hogs
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

### Solution

```bash
# Adjust compose resource limits
# deploy:
#   resources:
#     limits:
#       cpus: '0.5'
#       memory: 1G
#     reservations:
#       memory: 256M

# Clean up unused resources
docker system prune -a --volumes

# Restart containers to free memory
toolkit apps restart api

# Scale down non-critical services in staging
toolkit services down ollama
```

### Prevention

- Right-size containers: start conservative, monitor, adjust
- Set both limits and reservations
- Monitor resource usage trends in Grafana
- Set up OOM kill alerts

## n8n: Healthcheck Fails — No curl or wget in Image

### Root Cause

The `n8nio/n8n` image does not ship with `curl`, `wget`, or any other HTTP client. Standard healthcheck patterns using `CMD curl -f http://localhost:5678` fail immediately with:

```
exec: "curl": executable file not found in $PATH
```

### Solution

Use the Node.js runtime bundled in the image:

```yaml
healthcheck:
  test:
    - "CMD-SHELL"
    - "node -e \"require('http').get('http://localhost:5678/healthz', (r) => { process.exit(r.statusCode === 200 ? 0 : 1) })\""
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

### Prevention

Before writing a Docker healthcheck, verify which HTTP clients are available:

```bash
docker run --entrypoint sh n8nio/n8n -c "which curl wget node"
```

For any Node.js-based image, prefer the built-in `require('http').get(...)` pattern over installing curl.

---

## Volume Issues

### Problem

Data not persisting across container restarts, or volume mount errors.

### Diagnostic Steps

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect volume-name

# Check volume usage
docker system df -v

# Verify mount points
docker inspect container-name | grep -A 10 Mounts
```

### Solution

```bash
# Recreate volume
docker volume rm volume-name
docker volume create volume-name

# Fix permissions
docker exec container-name chown -R app:app /data

# Backup before removing
docker run --rm -v volume-name:/data -v $(pwd):/backup alpine tar czf /backup/backup.tar.gz /data

# Use bind mounts for development
# volumes:
#   - ./local-data:/app/data
```

### Prevention

- Use named volumes for data that must persist
- Use bind mounts for development (code, config)
- Always backup volumes before destructive operations
- Document volume ownership and permission requirements
