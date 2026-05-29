---
id: "kubelab-troubleshooting-build-failures"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Build Failures

Problems related to building KubeLab applications and Docker images.

## Out of Disk Space

### Problem

Builds fail due to insufficient disk space, often caused by accumulated Docker images and build cache.

### Diagnostic Steps

```bash
# Check available disk space
df -h

# Check Docker disk usage
docker system df
```

### Solution

```bash
# Clean up Docker resources
docker system prune -a
make clean

# Verify space was reclaimed
df -h
docker system df
```

### Prevention

- Schedule regular Docker cleanup: `docker system prune -a --volumes`
- Monitor disk usage in Grafana dashboards
- Set up alerts for disk usage thresholds

## Build Timeout

### Problem

Docker image builds exceed the configured timeout.

### Diagnostic Steps

```bash
# Check which stage is slow in the build
docker build --progress=plain .
```

### Solution

```bash
# Build single service instead of all at once
make api-build

# Increase timeout in docker-compose if needed
```

### Prevention

- Use multi-stage Docker builds to keep build stages lean
- Cache dependency layers effectively in Dockerfiles

## Dependency Issues

### Problem

Builds fail due to dependency resolution failures or cached stale dependencies.

### Diagnostic Steps

```bash
# Check build logs for specific dependency errors
make build 2>&1 | grep -i "error\|fail"
```

### Solution

```bash
# Clear all caches
make clean
docker builder prune -a

# Rebuild without cache
make build --no-cache
```

### Prevention

- Pin dependency versions in lock files
- Regularly update dependencies in a controlled manner
- Use Docker layer caching strategically

## CI/CD Build Failures

### Problem

GitHub Actions builds fail.

### Diagnostic Steps

```bash
# Check GitHub Actions logs
gh run list
gh run view <run-id> --log
```

### Solution

```bash
# Re-run failed jobs
gh run rerun <run-id>
```

### Prevention

- Keep CI environment consistent with local development
- Use version pinning for all CI dependencies

## Version Conflicts

### Problem

Version tag conflicts in the release pipeline.

### Diagnostic Steps

```bash
# Check git tags
git tag -l | tail -10
```

### Solution

```bash
# Manual version bump
git tag v1.2.3
git push origin v1.2.3
```

### Prevention

- Use automated versioning (semantic-release or similar)
- Protect version tags with branch protection rules
