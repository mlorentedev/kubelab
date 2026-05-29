---
id: "kubelab-troubleshooting-performance-tuning"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Performance Tuning

Optimization techniques and bottleneck identification for the KubeLab platform.

## Application-Level Optimization

### Go API

```bash
# Enable Go pprof profiling
# import _ "net/http/pprof"

# Use connection pooling
# db.SetMaxOpenConns(25)
# db.SetMaxIdleConns(10)

# Set memory limit
# GOMEMLIMIT=460MiB (90% of container limit)
```

### HTTP/2 and Protocol Optimization

```bash
# Enable HTTP/2
# Configure in Traefik: h2, http/1.1

# Implement rate limiting
# Configure in Traefik middlewares
```

### Static Asset Optimization

- Use CDN or Nginx caching for static assets
- Enable compression (gzip/brotli) in Nginx
- Set long cache TTLs with content hashing for cache busting

## Database Optimization

```bash
# Add indexes for common queries
docker exec postgres psql -U user -d db -c "CREATE INDEX idx_users_email ON users(email);"

# Analyze query performance
docker exec postgres psql -U user -d db -c "EXPLAIN ANALYZE SELECT * FROM table;"

# Tune connection pool
# max_connections = 100
# shared_buffers = 256MB

# Enable query logging
# log_min_duration_statement = 1000  (log queries > 1s)
```

## Caching Strategy

### Nginx Proxy Cache

```nginx
# proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m;
# proxy_cache my_cache;
# proxy_cache_valid 200 60m;
```

### Redis Caching (If Implemented)

```bash
# Check Redis stats
docker exec redis redis-cli INFO stats
```

### HTTP Caching Headers

```text
Cache-Control: public, max-age=31536000
ETag: "abc123"
```

## Bottleneck Identification

### CPU Profiling

```bash
# Profile API performance
curl -X POST http://localhost:8080/debug/pprof/profile?seconds=30 -o cpu.prof
go tools pprof -http=:9090 cpu.prof
```

### Database Slow Queries

```bash
# Find slowest queries
docker exec postgres psql -U user -d db -c "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"
```

### Network Latency

```bash
# Monitor network latency
mtr -r api.kubelab.live
traceroute api.kubelab.live
```

### Docker Overhead

```bash
# Analyze container resource usage
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
```

## Resource Allocation

### Container Right-Sizing

```yaml
# Start conservative, monitor, adjust:
# resources:
#   limits:
#     memory: 512M   # Start here
#     cpus: '0.5'
#   reservations:
#     memory: 256M
```

### Go Memory Management

```bash
# Use memory limits wisely
# GOMEMLIMIT=460MiB (90% of container limit)

# Monitor swap usage
docker stats --no-stream | grep api
free -h
```

### Scaling Strategy

- Scale horizontally for high load
- Use Docker Swarm or Kubernetes for multi-instance deployments

### Image Size Optimization

```dockerfile
# Use multi-stage builds
FROM golang:1.22 AS builder
# ... build steps ...
FROM alpine:latest
COPY --from=builder /app/binary /app/
```

## Host-Level Tuning

### File Descriptors

```bash
# Increase file descriptors
echo "fs.file-max = 100000" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Network Stack

```bash
# Tune network stack
echo "net.core.somaxconn = 65535" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.tcp_max_syn_backlog = 65535" | sudo tee -a /etc/sysctl.conf
```

### Transparent Huge Pages

```bash
# Disable transparent huge pages (if causing issues)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

### I/O Monitoring

```bash
# Monitor I/O wait
iostat -x 1 5
```

### File Watching (Development)

```bash
# Increase inotify watches for hot reload
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```
