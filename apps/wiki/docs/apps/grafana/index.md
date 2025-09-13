# 1.6 Grafana - Monitoring Stack

Comprehensive monitoring and observability solution using Grafana, Loki, Vector, and Uptime Kuma for system metrics, log aggregation, and uptime monitoring.

## What it is

This monitoring stack gives me complete visibility into the mlorente.dev infrastructure. Grafana provides beautiful dashboards to visualize system metrics, Loki aggregates logs from all services, Vector collects and routes telemetry data, and Uptime Kuma monitors service availability. Together, they help me spot issues before they become problems.

## Tech stack

- **Grafana** - Visualization and dashboards for metrics and logs
- **Loki** - Log aggregation system for centralized logging
- **Vector** - High-performance data collection and routing
- **Uptime Kuma** - Uptime monitoring and alerting
- **Docker** - Containerized deployment with persistent storage

## Key features

### Grafana dashboards
- **System metrics** - CPU, memory, disk, network monitoring
- **Application metrics** - Service response times and error rates
- **Log visualization** - Real-time log browsing and searching
- **Custom dashboards** - Tailored views for different services

### Log aggregation
- **Centralized logs** - All service logs in one place
- **Real-time streaming** - Live log tailing and search
- **Log retention** - Configurable retention policies
- **Structured logging** - JSON log parsing and indexing

### Uptime monitoring
- **Service availability** - HTTP/HTTPS endpoint monitoring
- **Response time tracking** - Latency measurements
- **Alert notifications** - Email/webhook alerts on downtime
- **Status pages** - Public uptime status display

## Configuration

### Docker Compose setup

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_SERVER_ROOT_URL=https://grafana.mlorente.dev
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    networks:
      - monitoring
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.grafana.rule=Host(`grafana.mlorente.dev`)"
      - "traefik.http.routers.grafana.entrypoints=websecure"
      - "traefik.http.routers.grafana.tls=true"
      - "traefik.http.routers.grafana.tls.certresolver=letsencrypt"

  loki:
    image: grafana/loki:latest
    container_name: loki
    restart: unless-stopped
    ports:
      - "3100:3100"
    volumes:
      - ./loki/config.yml:/etc/loki/local-config.yaml
      - loki_data:/loki
    networks:
      - monitoring
    command: -config.file=/etc/loki/local-config.yaml

  vector:
    image: vectordotdev/vector:latest
    container_name: vector
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./vector/config.yml:/etc/vector/vector.yaml
    networks:
      - monitoring
    depends_on:
      - loki

volumes:
  grafana_data:
  loki_data:

networks:
  monitoring:
    driver: bridge
  proxy:
    external: true
```

## Running the monitoring stack

### Development setup

```bash
# Start monitoring stack
make up-grafana

# Access Grafana dashboard
open http://grafana.mlorentedev.test

# Default credentials: admin/admin (change on first login)
```

### Configuration files

#### Grafana provisioning

```yaml
# grafana/provisioning/datasources/loki.yml
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
```

#### Loki configuration

```yaml
# loki/config.yml
auth_enabled: false

server:
  http_listen_port: 3100

ingester:
  lifecycler:
    address: 127.0.0.1
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/boltdb-shipper-active
    cache_location: /loki/boltdb-shipper-cache
    shared_store: filesystem
  filesystem:
    directory: /loki/chunks

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
```

#### Vector configuration

```yaml
# vector/config.yml
sources:
  docker_logs:
    type: docker_logs
    include_containers: ["api", "web", "blog", "wiki", "traefik"]

transforms:
  parse_logs:
    type: remap
    inputs: ["docker_logs"]
    source: |
      .timestamp = now()
      .service = .container_name
      .level = "info"

sinks:
  loki:
    type: loki
    inputs: ["parse_logs"]
    endpoint: http://loki:3100
    encoding:
      codec: json
    labels:
      service: "{{ service }}"
      container: "{{ container_name }}"
```

## Dashboards and monitoring

### Pre-built dashboards

1. **System Overview**
   - CPU, memory, disk usage
   - Network traffic
   - Container status

2. **Application Performance**
   - Response times
   - Error rates
   - Request volume

3. **Log Analysis**
   - Error log aggregation
   - Service-specific logs
   - Real-time log streaming

### Custom queries

#### System metrics
```promql
# CPU usage by container
rate(container_cpu_usage_seconds_total[5m]) * 100

# Memory usage
container_memory_usage_bytes / container_spec_memory_limit_bytes * 100

# Disk I/O
rate(container_fs_reads_bytes_total[5m])
```

#### Log queries
```logql
# Error logs from API
{service="api"} |= "ERROR"

# Recent application logs
{container_name=~"api|web|blog"} | json | level="error" 

# Request logs with response time
{service="traefik"} | json | duration > 1s
```

## Uptime monitoring

### Service monitoring setup

```yaml
# Uptime Kuma monitors
monitors:
  - name: "API Health"
    url: "https://api.mlorente.dev/health"
    interval: 60
    expected_status: 200
    
  - name: "Website"
    url: "https://mlorente.dev"
    interval: 60
    expected_status: 200
    
  - name: "Blog"
    url: "https://blog.mlorente.dev"
    interval: 60
    expected_status: 200
```

### Alert configuration

```yaml
# Alert notifications
notifications:
  - type: webhook
    url: "https://hooks.slack.com/services/..."
    conditions:
      - service_down
      - response_time_high
```

## Log management

### Log retention policies

```yaml
# Loki retention configuration
table_manager:
  retention_deletes_enabled: true
  retention_period: 168h  # 7 days
```

### Log aggregation

```bash
# View recent logs
curl -G -s "http://loki:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service="api"}' \
  --data-urlencode 'start=1h' | jq

# Search for errors
curl -G -s "http://loki:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service="api"} |= "ERROR"'
```

## Troubleshooting

### Grafana issues

**Cannot access Grafana:**
1. Check container status: `docker ps | grep grafana`
2. Verify port mapping: `docker port grafana`
3. Check logs: `docker logs grafana`
4. Verify Traefik routing

**Data source connection failed:**
1. Ensure Loki container is running
2. Check network connectivity: `docker exec grafana ping loki`
3. Verify Loki configuration and port
4. Check Grafana data source configuration

### Loki issues

**Logs not appearing:**
1. Check Vector configuration and status
2. Verify Loki ingestion: `curl http://loki:3100/ready`
3. Check log format and parsing
4. Review Vector logs: `docker logs vector`

**High disk usage:**
1. Check retention policies
2. Monitor data directory: `du -sh loki_data/`
3. Adjust retention period if needed
4. Clean old indices manually if required

## Local development URLs

When running locally with `make up-grafana`:
- **Grafana Dashboard**: http://grafana.mlorentedev.test
- **Direct access**: http://localhost:3000
- **Loki API**: http://localhost:3100
- **Uptime Kuma**: http://uptime.mlorentedev.test

Add these to your `/etc/hosts` file:
```
127.0.0.1 grafana.mlorentedev.test
127.0.0.1 uptime.mlorentedev.test
```

## Best practices

- **Dashboard organization** - Group related metrics in focused dashboards
- **Alert thresholds** - Set realistic thresholds to avoid alert fatigue
- **Log structuring** - Use consistent JSON logging across services
- **Data retention** - Balance storage costs with retention requirements
- **Performance monitoring** - Monitor Grafana/Loki resource usage

This monitoring stack provides comprehensive observability without requiring expensive commercial solutions, giving you professional-grade monitoring for your infrastructure.