# 4.6 How-To Guides - Quick Reference

## Common Tasks Index

- [🚀 Deployment](#-deployment)
- [🔧 Local Development](#-local-development)
- [🐛 Debugging](#-debugging)
- [📦 CI/CD](#-cicd)
- [🔐 Secrets and Variables](#-secrets-and-variables)
- [🌐 DNS and Domains](#-dns-and-domains)
- [🐳 Docker](#-docker)
- [📊 Monitoring](#-monitoring)
- [🤖 Automation](#-automation)

---

## 🚀 Deployment

### Deploy new version to staging

```bash
# 1. Download release
wget https://github.com/mlorente/mlorente.dev/releases/download/v1.2.0-rc.5/global-release-v1.2.0-rc.5.zip
unzip global-release-v1.2.0-rc.5.zip

# 2. Deploy
cd deployment
make deploy ENV=staging RELEASE_VERSION=v1.2.0-rc.5

# 3. Verify
curl -I https://staging.mlorente.dev
```

### Emergency rollback

```bash
# Automatic rollback
make emergency-rollback ENV=production

# Manual rollback
make deploy ENV=production RELEASE_VERSION=v1.1.0
```

### Verify deployment status

```bash
# Container status
make status ENV=production

# Real-time logs
make logs ENV=production

# Verify endpoint health
curl -f https://mlorente.dev/health
curl -f https://api.mlorente.dev/health
curl -f https://blog.mlorente.dev
```

---

## 🔧 Local Development

### Start complete environment

```bash
# Initial setup (first time only)
make install-precommit-hooks
make create-network

# Start everything
make up

# Local URLs
# http://site.mlorentedev.test
# http://blog.mlorentedev.test
# http://api.mlorentedev.test
# http://traefik.mlorentedev.test:8080
```

### Start only one app

```bash
# Web only
make up-web

# Blog only
make up-blog

# API only
make up-api
```

### Rebuild from scratch

```bash
make down
docker system prune -af --volumes
make up --force-recreate
```

### Add new local domain

```bash
# Add to /etc/hosts
echo "127.0.0.1 nueva-app.mlorentedev.test" | sudo tee -a /etc/hosts

# Or configure dnsmasq
echo "address=/.mlorentedev.test/127.0.0.1" | sudo tee /etc/dnsmasq.d/mlorente
sudo systemctl restart dnsmasq
```

---

## 🐛 Debugging

### View logs of a specific app

```bash
# API logs
docker logs $(docker ps -q -f name=api) -f

# Traefik logs
docker logs $(docker ps -q -f name=traefik) -f

# Logs with timestamp
docker logs $(docker ps -q -f name=web) -f -t
```

### Enter container for debugging

```bash
# Enter API
docker exec -it $(docker ps -q -f name=api) sh

# Enter web container
docker exec -it $(docker ps -q -f name=web) sh

# Execute specific command
docker exec $(docker ps -q -f name=api) ps aux
```

### Verify connectivity between containers

```bash
# From web to API
docker exec $(docker ps -q -f name=web) wget -qO- http://api:8080/health

# From API to blog
docker exec $(docker ps -q -f name=api) curl -I http://blog:4000
```

### Local DNS problems

```bash
# Verify DNS resolution
nslookup site.mlorentedev.test

# Test direct connectivity
curl -H "Host: site.mlorentedev.test" http://localhost

# Clear DNS cache
sudo systemctl flush-dns  # macOS: sudo dscacheutil -flushcache
```

---

## 📦 CI/CD

### Trigger manual build

```bash
# From GitHub CLI
gh workflow run "CI Pipeline" --ref develop

# View workflow status
gh run list --limit 10

# View specific run logs
gh run view <run-id> --log
```

### Verify which apps would change

```bash
# See files changed since last commit
git diff --name-only HEAD~1

# Filter by apps
git diff --name-only HEAD~1 | grep -E "(apps/blog|apps/api|apps/web)"

# Simulate change detection
dorny/paths-filter@v3  # use action locally
```

### Debug version calculation

```bash
# View latest tag
git tag --sort=-version:refname | head -5

# View commits since last tag
git log $(git tag --sort=-version:refname | head -1)..HEAD --oneline

# Simulate version calculation
./scripts/calculate-version.sh develop
```

### Re-run failed job

```bash
# Specific re-run
gh run rerun <run-id>

# Re-run failed jobs only
gh run rerun <run-id> --failed
```

---

## 🔐 Secrets and Variables

### List configured secrets

```bash
# View secrets (hidden values)
gh secret list

# View repo variables
gh variable list
```

### Update secret

```bash
# Update individual secret
gh secret set DOCKERHUB_TOKEN

# From file
gh secret set DOCKERHUB_TOKEN < token.txt

# For multiple environments
gh secret set API_KEY --env production
gh secret set API_KEY --env staging
```

### Sync .env with GitHub Secrets

```bash
# Automatic script (if exists)
make setup-secrets

# Manual
gh secret set DOCKERHUB_USERNAME --body "$(grep DOCKERHUB_USERNAME .env | cut -d'=' -f2)"
gh secret set N8N_WEBHOOK_URL --body "$(grep N8N_WEBHOOK_URL .env | cut -d'=' -f2)"
```

### Verify variables at runtime

```bash
# En GitHub Actions (debug step)
- name: Debug env vars
  run: |
    echo "Branch: ${{ github.ref_name }}"
    echo "Registry: ${{ vars.REGISTRY_PREFIX || 'mlorente' }}"
    echo "Has webhook: ${{ secrets.N8N_WEBHOOK_URL != '' }}"
```

---

## 🌐 DNS and Domains

### Verify DNS configuration

```bash
# Verify A records
dig mlorente.dev A
dig blog.mlorente.dev A
dig api.mlorente.dev A

# Verify DNS propagation
nslookup mlorente.dev 8.8.8.8
nslookup mlorente.dev 1.1.1.1
```

### Verify SSL certificates

```bash
# Verify certificate
openssl s_client -connect mlorente.dev:443 -servername mlorente.dev

# View expiration dates
echo | openssl s_client -connect mlorente.dev:443 2>/dev/null | openssl x509 -noout -dates

# Verify complete chain
curl -vvI https://mlorente.dev 2>&1 | grep -E "(SSL|TLS|certificate)"
```

### Regenerate Traefik certificates

```bash
# On the server
docker exec $(docker ps -q -f name=traefik) rm /acme.json
docker restart $(docker ps -q -f name=traefik)

# Verify renewal logs
docker logs $(docker ps -q -f name=traefik) | grep -i acme
```

---

## 🐳 Docker

### Clean Docker system

```bash
# Clean unused images
docker system prune -f

# Clean everything (images, volumes, networks)
docker system prune -af --volumes

# Clean only dangling images
docker image prune -f
```

### Inspect Docker resources

```bash
# View resource usage
docker stats --no-stream

# Ver imágenes por tamaño
docker images --format "table {{.Repository}}	{{.Tag}}	{{.Size}}" | sort -k3 -h

# Ver volúmenes
docker volume ls
docker volume inspect mlorente_traefik-data
```

### Multi-arch builds locales

```bash
# Crear builder multi-arch
docker buildx create --use --name multiarch

# Build para ambas arquitecturas
docker buildx build --platform linux/amd64,linux/arm64 -t test:latest .

# Push multi-arch
docker buildx build --platform linux/amd64,linux/arm64 -t user/image:tag --push .
```

### Verificar health checks

```bash
# Ver estado de health checks
docker ps --format "table {{.Names}}	{{.Status}}"

# Inspeccionar health check de contenedor
docker inspect $(docker ps -q -f name=web) | jq '.[0].State.Health'
```

---

## 📊 Monitoring

### Verify performance metrics

```bash
# CPU y memoria por contenedor
docker stats --format "table {{.Container}}	{{.CPUPerc}}	{{.MemUsage}}	{{.NetIO}}"

# Uso de disco
df -h /opt/mlorente-*
du -sh /var/lib/docker/

# Procesos en contenedor
docker exec $(docker ps -q -f name=api) ps aux
```

### Traefik access logs

```bash
# Ver últimos accesos
docker logs $(docker ps -q -f name=traefik) | tail -100

# Filtrar errores 4xx/5xx
docker logs $(docker ps -q -f name=traefik) | grep -E "(4[0-9]{2}|5[0-9]{2})"

# Seguir logs en tiempo real
docker logs $(docker ps -q -f name=traefik) -f
```

### Health endpoints

```bash
# Script de verificación rápida
check_endpoints() {
  endpoints=(
    "https://mlorente.dev"
    "https://blog.mlorente.dev"
    "https://api.mlorente.dev/health"
  )
  
  for endpoint in "${endpoints[@]}"; do
    if curl -f -s "$endpoint" > /dev/null; then
      echo "✅ $endpoint"
    else
      echo "❌ $endpoint"
    fi
  done
}

check_endpoints
```

### Basic alerts

```bash
# Script de monitoreo simple
#!/bin/bash
# monitor-containers.sh

containers=("traefik" "web" "blog" "api")

for container in "${containers[@]}"; do
  if ! docker ps | grep -q "$container"; then
    echo "🚨 ALERT: Container $container is not running"
    # Aquí podrías enviar webhook o email
  fi
done
```

---

## ⚡ Utility Scripts

### All-in-one development script

```bash
#!/bin/bash
# dev-setup.sh

echo "🚀 Setting up mlorente.dev development environment..."

# Verificar dependencias
make check

# Setup inicial
make install-precommit-hooks
make create-network

# Levantar servicios
make up

# Verificar que todo funciona
sleep 10
curl -I http://site.mlorentedev.test && echo "✅ Web OK"
curl -I http://blog.mlorentedev.test && echo "✅ Blog OK"  
curl -I http://api.mlorentedev.test && echo "✅ API OK"

echo "✨ Development environment ready!"
```

### Quick deploy script

```bash
#!/bin/bash
# quick-deploy.sh

VERSION=${1:-latest}
ENV=${2:-staging}

echo "🚀 Deploying $VERSION to $ENV..."

# Descargar si es release específico
if [[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  wget -q "https://github.com/mlorente/mlorente.dev/releases/download/$VERSION/global-release-$VERSION.zip"
  unzip -q "global-release-$VERSION.zip"
  cd deployment
fi

# Deploy
make deploy ENV=$ENV RELEASE_VERSION=$VERSION

# Verify
echo "🔍 Verifying deployment..."
make status ENV=$ENV

echo "✅ Deployment complete!"
```

---

## 🔍 Quick Search

### By symptom

| Síntoma | Comando | Referencia |
|---------|---------|------------|
| "Port already in use" | `sudo lsof -i :80` | [Debugging](#-debugging) |
| "Network not found" | `make create-network` | [Docker](#-docker) |
| "Domain not resolving" | `nslookup site.mlorentedev.test` | [DNS](#-dns-y-dominios) |
| "Container not starting" | `docker logs container_name` | [Debugging](#-debugging) |
| "Build failing" | `gh run view <run-id> --log` | [CI/CD](#-cicd) |
| "SSL certificate error" | `curl -vvI https://domain.com` | [DNS](#-dns-y-dominios) |

### By task

| Tarea | Comando | Tiempo estimado |
|-------|---------|----------------|
| Setup completo local | `make install-precommit-hooks && make up` | 5-10 min |
| Deploy a staging | `make deploy ENV=staging` | 2-3 min |
| Rollback producción | `make emergency-rollback ENV=production` | 1 min |
| Ver logs aplicación | `make logs APP=api` | Inmediato |
| Limpiar Docker | `docker system prune -af` | 1-2 min |

---

## 🤖 Automation

### General policy

- Todas las salidas se generan en `docs/AUTOMATION/`  
- Subcarpetas: `reports/`, `indexes/`, `changelogs/`, `adrs/`, `digests/`, `security/`  
- Una tarea → un output (archivo o diff).  
- Los PRs se hacen siempre manualmente.  
- Usar Conventional Commits (`docs:`, `chore:`, `fix:`, `ci:`, `feat:`).  
- Idempotencia: sin cambios, diff vacío.  

### Common tasks

```bash
# Normalizar READMEs
Task: Normalize and improve README.md for module {{path}}.
Output: unified diff only

# Generar índices
Task: Sync READMEs to wiki/docs and generate indexes with tables.
Output: markdown in docs/AUTOMATION/indexes

# Generar CHANGELOG
Task: Generate CHANGELOG from Conventional Commits since last tag.
Output: docs/AUTOMATION/changelogs/CHANGELOG-<date>.md
```

### Audits

```bash
# Deriva de .env
Task: Compare all .env.example files and report missing/extra keys.
Output: docs/AUTOMATION/reports/env-drift.md

# Enlaces rotos
Task: Scan docs/** and apps/wiki/docs/** for broken links/anchors.
Output: diff + docs/AUTOMATION/reports/broken-links.md

# Auditoría Traefik
Task: Audit traefik labels for TLS, routers, entrypoints, duplicates.
Output: docs/AUTOMATION/reports/traefik-audit.md
```

### Maintenance scripts

```bash
# Inventario Docker
Task: Extract services from docker-compose.*.yml.
Output: docs/AUTOMATION/indexes/services-inventory.md

# Targets Makefile
Task: Parse Makefiles and generate documentation of targets.
Output: docs/AUTOMATION/indexes/make-targets.md

# Health Ansible
Task: Validate Ansible playbooks syntax and variables.
Output: docs/AUTOMATION/reports/ansible-health.md
```

### Security

```bash
# Escaneo secretos
Task: Run secret scan and review .gitignore coverage.
Output: docs/AUTOMATION/security/secrets-scan.md

# Licencias
Task: Check license headers in .go, .sh, .astro files.
Output: docs/AUTOMATION/reports/license-check.md

# Workflows CI
Task: Audit GitHub Actions workflows (permissions, tags, cache).
Output: docs/AUTOMATION/reports/ci-audit.md
```

### Summaries and ADRs

```bash
# Weekly Ops Digest
Task: Summarize weekly ops (PRs, issues, docs, next steps).
Output: docs/AUTOMATION/digests/ops-digest-YYYY-WW.md

# ADRs
Task: Create ADR with context, decision, consequences.
Output: docs/AUTOMATION/adrs/ADR-<n>-<slug>.md
```

---

*💡 **Tip**: Bookmark this page in your browser for quick access during development and operations.*
