# 1.9 Loki - Log Aggregation System

High-performance log aggregation system that collects, stores, and queries logs from across the mlorente.dev infrastructure. Works seamlessly with Grafana for log visualization and analysis.

## What it is

Loki is the log aggregation backbone for the mlorente.dev monitoring stack. It ingests logs from all services, stores them efficiently, and provides fast querying capabilities. I use it because it integrates perfectly with Grafana and gives me centralized log management without the complexity of Elasticsearch.

## Tech stack

- **Loki** - Log aggregation system by Grafana Labs
- **LogQL** - Query language for searching logs
- **Vector** - High-performance log collection agent
- **Docker** - Containerized deployment
- **Grafana integration** - Native log visualization

## Key features

### Log aggregation
- **Multi-tenant architecture** - Separate logs by service and environment
- **Efficient storage** - Compressed and indexed log storage
- **Stream processing** - Real-time log ingestion and processing
- **Label-based indexing** - Fast queries using labels instead of full-text indexing

### Query capabilities
- **LogQL queries** - Powerful query language for log analysis
- **Real-time search** - Live log tailing and filtering
- **Aggregation functions** - Count, rate, and statistical operations
- **Regex support** - Pattern matching and extraction

## Configuration

### Docker Compose setup

```yaml
services:
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

volumes:
  loki_data:

networks:
  monitoring:
    driver: bridge
```

### Basic configuration

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

## Running Loki

### Development setup

```bash
# Start Loki
make up-grafana  # Includes Loki in the monitoring stack

# Check if Loki is ready
curl http://localhost:3100/ready

# Check metrics
curl http://localhost:3100/metrics
```

## Log ingestion

### Vector configuration for log collection

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

## Querying logs

### LogQL examples

```logql
# All logs from API service
{service="api"}

# Error logs from all services
{job="docker_logs"} |= "ERROR"

# Logs from specific container
{container_name="api"} | json | level="error"

# Count error rate over time
sum by (service) (rate({level="error"}[5m]))

# Search for specific patterns
{service="traefik"} |~ "failed|timeout|error"
```

### API queries

```bash
# Query logs via API
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service="api"}' \
  --data-urlencode 'start=1h' | jq

# Search for errors
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service="api"} |= "ERROR"'
```

## Integration with Grafana

### Data source configuration

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

### Common dashboard queries

- **Log volume**: `sum by (service) (rate({job="docker_logs"}[5m]))`
- **Error rate**: `sum by (service) (rate({level="error"}[1m]))`
- **Service logs**: `{service="$service"} | json`

## Troubleshooting

### Loki not starting
1. Check configuration file syntax: `docker logs loki`
2. Verify storage permissions: `docker exec loki ls -la /loki`
3. Check disk space: `df -h`

### Logs not appearing
1. Verify Vector is sending logs: `curl http://localhost:8686/health`
2. Check Loki ingestion: `curl http://localhost:3100/ready`
3. Review Vector configuration and restart if needed

### High disk usage
1. Check retention policy in config
2. Monitor data directory size: `du -sh loki_data/`
3. Clean old logs if needed

## Local development URLs

When running with the monitoring stack:
- **Loki API**: http://localhost:3100
- **Loki metrics**: http://localhost:3100/metrics
- **Grafana with Loki**: http://grafana.mlorentedev.test

## Best practices

- **Structured logging** - Use consistent JSON format across services
- **Appropriate labels** - Don't over-index, use service and environment labels
- **Log retention** - Balance storage costs with retention requirements
- **Query optimization** - Use labels effectively to reduce query scope

Loki provides powerful log aggregation capabilities that scale well and integrate seamlessly with the rest of the monitoring stack.