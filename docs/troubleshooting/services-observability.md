---
id: "kubelab-troubleshooting-services-observability"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Observability Stack Troubleshooting

Service-specific troubleshooting for Grafana, Loki, and monitoring in KubeLab.

## Grafana

### Cannot Login

#### Problem

Unable to authenticate to Grafana.

#### Diagnostic Steps

```bash
# Check environment variables
docker exec grafana env | grep GF_

# Verify database
docker exec grafana ls -la /var/lib/grafana/grafana.db
```

#### Solution

```bash
# Reset admin password
docker exec -it grafana grafana-cli admin reset-admin-password newpassword
```

#### Prevention

- Store Grafana credentials in Vaultwarden
- Document default credentials in secure location

### Dashboards Not Loading

#### Problem

Grafana dashboards are blank or show "No data" errors.

#### Diagnostic Steps

```bash
# Check provisioning
docker exec grafana ls -la /etc/grafana/provisioning/dashboards/
docker exec grafana ls -la /var/lib/grafana/dashboards/

# Verify data source
docker exec grafana cat /etc/grafana/provisioning/datasources/loki.yml

# Test Loki connection
docker exec grafana curl http://loki:3100/ready
```

#### Solution

```bash
# Re-provision dashboards
docker exec grafana ls -la /var/lib/grafana/dashboards/
docker cp dashboard.json grafana:/var/lib/grafana/dashboards/

# Reset Grafana database
docker volume rm grafana-data
toolkit services restart grafana

# Import dashboard via API
curl -X POST http://admin:admin@localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @dashboard.json
```

#### Prevention

- Version control all dashboard JSON files
- Use provisioning for consistent dashboard deployment

### No Metrics Available

#### Problem

Metrics endpoints are not returning data to Grafana.

#### Diagnostic Steps

```bash
# Verify Loki is running
toolkit services logs loki

# Test log ingestion
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams": [{"stream": {"app": "test"}, "values": [["1234567890000000000", "test message"]]}]}'

# Check Vector pipeline (if using)
docker logs vector-container
```

#### Solution

```bash
# Verify Grafana provisioning
docker exec grafana ls -la /etc/grafana/provisioning/datasources/

# Reload datasources
curl -X POST http://admin:admin@localhost:3000/api/admin/provisioning/datasources/reload

# Check metric format
curl http://localhost:8080/metrics | grep -E "^[a-z_]+"
```

### Dashboard Access Issues

#### Problem

Cannot access Grafana dashboards due to permissions.

#### Diagnostic Steps

```bash
# Check Grafana health
curl http://localhost:3000/api/health

# Verify authentication config
cat infra/compose/services/observability/grafana/.env.dev | grep GF_AUTH

# Check dashboard permissions
docker exec grafana-db psql -U grafana -c "SELECT * FROM dashboard;"
```

#### Solution

```bash
# Disable auth temporarily for debugging
# GF_AUTH_ANONYMOUS_ENABLED=true
# GF_AUTH_ANONYMOUS_ORG_ROLE=Admin

toolkit services restart grafana
```

## Loki

### Log Ingestion Failing

#### Problem

Logs are not being ingested into Loki.

#### Diagnostic Steps

```bash
# Check Loki health
curl http://localhost:3100/ready
curl http://localhost:3100/metrics

# Verify storage
docker exec loki ls -la /loki/

# Check retention configuration
docker exec loki cat /etc/loki/config.yml | grep retention
```

#### Solution

```bash
# Restart Loki
toolkit services restart loki

# Test manual log push
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"job":"test"},"values":[["'$(date +%s000000000)'","test log"]]}]}'
```

### Query Performance Issues

#### Problem

Loki queries are slow or timing out.

#### Diagnostic Steps

```bash
# Check index size
docker exec loki du -sh /loki/index/

# Check index cache settings
grep -A 10 "index_cache" infra/compose/services/observability/loki/config/loki-config.yml
```

#### Solution

- Optimize queries: use smaller time ranges
- Use labels efficiently in queries: `{app="api"} |= "error"`
- Consider increasing index cache settings in Loki config

#### Prevention

- Design label cardinality carefully (avoid high-cardinality labels)
- Set appropriate retention periods
- Monitor Loki resource usage

## Log Aggregation Problems

### Problem

Logs not appearing in Loki/Grafana from application containers.

### Diagnostic Steps

```bash
# Check Loki ingestion
curl http://localhost:3100/loki/api/v1/labels

# Verify log driver
docker inspect container-name | grep LogConfig

# Check Vector pipeline (if used)
docker logs vector-container | grep error
```

### Solution

```bash
# Configure Docker logging driver
# logging:
#   driver: "loki"
#   options:
#     loki-url: "http://loki:3100/loki/api/v1/push"

# Restart Loki
toolkit services restart loki

# Check Promtail configuration (if used)
docker exec promtail cat /etc/promtail/config.yml
```

### Prevention

- Standardize logging driver configuration across all services
- Monitor log ingestion rate in Grafana
- Set up alerts for ingestion failures
