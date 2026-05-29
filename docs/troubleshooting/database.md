---
id: "kubelab-troubleshooting-database"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Database & Data Issues

Problems related to PostgreSQL databases and data persistence in KubeLab.

## Database Connection Failed

### Problem

Applications cannot connect to the PostgreSQL database.

### Diagnostic Steps

```bash
# Check database container is running
docker ps | grep postgres
make logs APP=postgres

# Test connection directly
docker exec -it postgres_container psql -U user -d database
```

### Solution

```bash
# Restart the database container
toolkit apps restart postgres

# Check database logs for errors
make logs APP=postgres
```

### Prevention

- Implement connection retry logic in applications
- Monitor database container health
- Set up alerts for database connection failures

## Data Loss Prevention

### Problem

Risk of data loss during operations or failures.

### Diagnostic Steps

```bash
# List existing backups
ls -la backups/
```

### Solution

```bash
# Backup before any risky operations
make backup ENV=production

# Verify backup integrity
tar tzf backups/backup-<date>.tar.gz | head
```

### Prevention

- Always backup before destructive operations
- Automate regular backups with scheduled jobs
- Test backup restoration periodically
- Store backups in a separate location from the database

## Database Performance

### Problem

Slow queries or connection pool exhaustion.

### Diagnostic Steps

```bash
# Check active connections
docker exec postgres-container psql -c "SELECT * FROM pg_stat_activity;"

# Check slow queries (if pg_stat_statements enabled)
docker exec postgres psql -U user -d db -c "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"

# Analyze query performance
docker exec postgres psql -U user -d db -c "EXPLAIN ANALYZE SELECT * FROM table;"
```

### Solution

```bash
# Add indexes for common queries
docker exec postgres psql -U user -d db -c "CREATE INDEX idx_users_email ON users(email);"

# Tune connection pool settings
# max_connections = 100
# shared_buffers = 256MB

# Enable query logging for analysis
# log_min_duration_statement = 1000  (log queries > 1s)
```

### Prevention

- Monitor query performance regularly
- Set up alerts for connection pool usage
- Use connection pooling (e.g., PgBouncer) for high-load services
- Review query plans during development
