# 4.4 Troubleshooting

Common issues and solutions for mlorente.dev.

## Quick Diagnostics

```bash
# Check overall status
make status

# Check specific service
make logs APP=api

# Check all logs
make logs

# Docker health check
docker ps -a
docker system df
```

## Common Issues

### Services won't start

**Docker daemon not running:**
```bash
sudo systemctl start docker
```

**Port conflicts:**
```bash
# Check what's using port 80/443
sudo netstat -tulpn | grep :80
sudo netstat -tulpn | grep :443

# Stop conflicting services
sudo systemctl stop nginx apache2
```

**Permission issues:**
```bash
# Fix ownership
sudo chown -R $USER:$USER .
sudo usermod -aG docker $USER
# Logout and login again
```

### SSL/HTTPS Problems

**Certificate not working:**
```bash
# Check Traefik logs
make logs APP=traefik

# Verify DNS
dig mlorente.dev
curl -vvI https://mlorente.dev
```

**Let's Encrypt rate limits:**
- Use staging environment first
- Check DNS propagation before deploying
- Wait 1 hour between failed attempts

### Build Failures

**Out of disk space:**
```bash
# Clean up Docker
docker system prune -a
make clean

# Check space
df -h
docker system df
```

**Build timeout:**
```bash
# Increase timeout in docker-compose
# Or build single service
make api-build
```

**Dependencies issues:**
```bash
# Clear caches
make clean
docker builder prune -a

# Rebuild without cache
make build --no-cache
```

### Deployment Issues

**Deploy fails:**
```bash
# Check server connection
ssh mlorente-prod "docker ps"

# Check environment
ssh mlorente-prod "cat /opt/mlorente.dev/.env.production"

# Manual deploy
ssh mlorente-prod
cd /opt/mlorente.dev
git pull
make deploy ENV=production
```

**Services down after deploy:**
```bash
# Check container status
make status ENV=production

# Restart specific service
make restart APP=api ENV=production

# Emergency rollback
make emergency-rollback ENV=production
```

### Database/Data Issues

**Database connection failed:**
```bash
# Check database container
docker ps | grep postgres
make logs APP=postgres

# Test connection
docker exec -it postgres_container psql -U user -d database
```

**Data loss prevention:**
```bash
# Backup before operations
make backup ENV=production

# List backups
ls -la backups/
```

### Performance Issues

**High memory usage:**
```bash
# Check resource usage
docker stats
htop

# Restart memory-heavy services
make restart APP=api
```

**Slow response:**
```bash
# Check logs for errors
make logs APP=traefik | grep error
make logs APP=nginx | grep error

# Monitor response times
curl -w "@curl-format.txt" -o /dev/null https://mlorente.dev
```

## Development Issues

**Hot reload not working:**
```bash
# Check file watching limits
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Restart dev server
make web-dev
```

**Port already in use:**
```bash
# Find process using port
lsof -i :3000
kill -9 <PID>

# Or change port in docker-compose.dev.yml
```

## CI/CD Issues

**Build failing:**
```bash
# Check GitHub Actions logs
gh run list
gh run view <run-id> --log

# Re-run failed jobs
gh run rerun <run-id>
```

**Version conflicts:**
```bash
# Check git tags
git tag -l | tail -10

# Manual version bump
git tag v1.0.1
git push origin v1.0.1
```

## Emergency Procedures

**Complete system down:**
```bash
# Quick restart
make down && make up

# Nuclear option
docker kill $(docker ps -q)
docker rm $(docker ps -aq)
make clean && make up
```

**Rollback deployment:**
```bash
make emergency-rollback ENV=production
```

**Restore from backup:**
```bash
make restore BACKUP=backup-20240301.tar.gz ENV=production
```

## Getting Help

1. Check logs first: `make logs`
2. Search GitHub issues
3. Check documentation in `docs/`
4. Verify environment configuration