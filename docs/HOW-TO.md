# Guías How-To - Referencia Rápida

## Índice de Tareas Comunes

- [🚀 Despliegue](#-despliegue)
- [🔧 Desarrollo Local](#-desarrollo-local)
- [🐛 Debugging](#-debugging)
- [📦 CI/CD](#-cicd)
- [🔐 Secretos y Variables](#-secretos-y-variables)
- [🌐 DNS y Dominios](#-dns-y-dominios)
- [🐳 Docker](#-docker)
- [📊 Monitorización](#-monitorización)
- [🤖 Automation](#-automation)

---

## 🚀 Despliegue

### Desplegar nueva versión a staging

```bash
# 1. Descargar release
wget https://github.com/mlorente/mlorente.dev/releases/download/v1.2.0-rc.5/global-release-v1.2.0-rc.5.zip
unzip global-release-v1.2.0-rc.5.zip

# 2. Desplegar
cd deployment
make deploy ENV=staging RELEASE_VERSION=v1.2.0-rc.5

# 3. Verificar
curl -I https://staging.mlorente.dev
```

### Rollback de emergencia

```bash
# Rollback automático
make emergency-rollback ENV=production

# Rollback manual
make deploy ENV=production RELEASE_VERSION=v1.1.0
```

### Verificar estado del despliegue

```bash
# Estado de contenedores
make status ENV=production

# Logs en tiempo real
make logs ENV=production

# Verificar salud de endpoints
curl -f https://mlorente.dev/health
curl -f https://api.mlorente.dev/health
curl -f https://blog.mlorente.dev
```

---

## 🔧 Desarrollo Local

### Levantar entorno completo

```bash
# Setup inicial (solo primera vez)
make env-setup
make create-network

# Levantar todo
make up

# URLs locales
# http://site.mlorentedev.test
# http://blog.mlorentedev.test
# http://api.mlorentedev.test
# http://traefik.mlorentedev.test:8080
```

### Levantar solo una app

```bash
# Solo web
make up-web

# Solo blog
make up-blog

# Solo API
make up-api
```

### Reconstruir desde cero

```bash
make down
docker system prune -af --volumes
make up --force-recreate
```

### Añadir nuevo dominio local

```bash
# Añadir a /etc/hosts
echo "127.0.0.1 nueva-app.mlorentedev.test" | sudo tee -a /etc/hosts

# O configurar dnsmasq
echo "address=/.mlorentedev.test/127.0.0.1" | sudo tee /etc/dnsmasq.d/mlorente
sudo systemctl restart dnsmasq
```

---

## 🐛 Debugging

### Ver logs de una app específica

```bash
# Logs de API
docker logs $(docker ps -q -f name=api) -f

# Logs de Traefik
docker logs $(docker ps -q -f name=traefik) -f

# Logs con timestamp
docker logs $(docker ps -q -f name=web) -f -t
```

### Entrar en contenedor para debug

```bash
# Entrar en API
docker exec -it $(docker ps -q -f name=api) sh

# Entrar en contenedor web
docker exec -it $(docker ps -q -f name=web) sh

# Ejecutar comando específico
docker exec $(docker ps -q -f name=api) ps aux
```

### Verificar conectividad entre contenedores

```bash
# Desde web a API
docker exec $(docker ps -q -f name=web) wget -qO- http://api:8080/health

# Desde API a blog
docker exec $(docker ps -q -f name=api) curl -I http://blog:4000
```

### Problemas de DNS local

```bash
# Verificar resolución DNS
nslookup site.mlorentedev.test

# Probar conectividad directa
curl -H "Host: site.mlorentedev.test" http://localhost

# Limpiar DNS cache
sudo systemctl flush-dns  # macOS: sudo dscacheutil -flushcache
```

---

## 📦 CI/CD

### Triggear build manual

```bash
# Desde GitHub CLI
gh workflow run "CI Pipeline" --ref develop

# Ver estado de workflows
gh run list --limit 10

# Ver logs de run específico
gh run view <run-id> --log
```

### Verificar qué apps cambiarían

```bash
# Ver archivos cambiados desde último commit
git diff --name-only HEAD~1

# Filtrar por apps
git diff --name-only HEAD~1 | grep -E "(apps/blog|apps/api|apps/web)"

# Simular detección de cambios
dorny/paths-filter@v3  # usar action localmente
```

### Debug version calculation

```bash
# Ver último tag
git tag --sort=-version:refname | head -5

# Ver commits desde último tag
git log $(git tag --sort=-version:refname | head -1)..HEAD --oneline

# Simular cálculo de versión
./scripts/calculate-version.sh develop
```

### Re-ejecutar job fallido

```bash
# Re-run específico
gh run rerun <run-id>

# Re-run solo jobs fallidos
gh run rerun <run-id> --failed
```

---

## 🔐 Secretos y Variables

### Listar secretos configurados

```bash
# Ver secretos (valores ocultos)
gh secret list

# Ver variables del repo
gh variable list
```

### Actualizar secret

```bash
# Actualizar secret individual
gh secret set DOCKERHUB_TOKEN

# Desde archivo
gh secret set DOCKERHUB_TOKEN < token.txt

# Para múltiples environments
gh secret set API_KEY --env production
gh secret set API_KEY --env staging
```

### Sincronizar .env con GitHub Secrets

```bash
# Script automático (si existe)
make setup-secrets

# Manual
gh secret set DOCKERHUB_USERNAME --body "$(grep DOCKERHUB_USERNAME .env | cut -d'=' -f2)"
gh secret set N8N_WEBHOOK_URL --body "$(grep N8N_WEBHOOK_URL .env | cut -d'=' -f2)"
```

### Verificar variables en runtime

```bash
# En GitHub Actions (debug step)
- name: Debug env vars
  run: |
    echo "Branch: ${{ github.ref_name }}"
    echo "Registry: ${{ vars.REGISTRY_PREFIX || 'mlorente' }}"
    echo "Has webhook: ${{ secrets.N8N_WEBHOOK_URL != '' }}"
```

---

## 🌐 DNS y Dominios

### Verificar configuración DNS

```bash
# Verificar records A
dig mlorente.dev A
dig blog.mlorente.dev A
dig api.mlorente.dev A

# Verificar propagación DNS
nslookup mlorente.dev 8.8.8.8
nslookup mlorente.dev 1.1.1.1
```

### Verificar certificados SSL

```bash
# Verificar certificado
openssl s_client -connect mlorente.dev:443 -servername mlorente.dev

# Ver fechas de expiración
echo | openssl s_client -connect mlorente.dev:443 2>/dev/null | openssl x509 -noout -dates

# Verificar cadena completa
curl -vvI https://mlorente.dev 2>&1 | grep -E "(SSL|TLS|certificate)"
```

### Regenerar certificados Traefik

```bash
# En el servidor
docker exec $(docker ps -q -f name=traefik) rm /acme.json
docker restart $(docker ps -q -f name=traefik)

# Verificar logs de renovación
docker logs $(docker ps -q -f name=traefik) | grep -i acme
```

---

## 🐳 Docker

### Limpiar sistema Docker

```bash
# Limpiar imágenes no utilizadas
docker system prune -f

# Limpiar todo (imágenes, volúmenes, networks)
docker system prune -af --volumes

# Limpiar solo imágenes colgantes
docker image prune -f
```

### Inspeccionar recursos Docker

```bash
# Ver uso de recursos
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

## 📊 Monitorización

### Verificar métricas de rendimiento

```bash
# CPU y memoria por contenedor
docker stats --format "table {{.Container}}	{{.CPUPerc}}	{{.MemUsage}}	{{.NetIO}}"

# Uso de disco
df -h /opt/mlorente-*
du -sh /var/lib/docker/

# Procesos en contenedor
docker exec $(docker ps -q -f name=api) ps aux
```

### Logs de acceso Traefik

```bash
# Ver últimos accesos
docker logs $(docker ps -q -f name=traefik) | tail -100

# Filtrar errores 4xx/5xx
docker logs $(docker ps -q -f name=traefik) | grep -E "(4[0-9]{2}|5[0-9]{2})"

# Seguir logs en tiempo real
docker logs $(docker ps -q -f name=traefik) -f
```

### Endpoints de salud

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

### Alertas básicas

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

## ⚡ Scripts de Utilidad

### Script all-in-one para desarrollo

```bash
#!/bin/bash
# dev-setup.sh

echo "🚀 Setting up mlorente.dev development environment..."

# Verificar dependencias
make check

# Setup inicial
make env-setup
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

### Script de deploy rápido

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

## 🔍 Búsqueda Rápida

### Por síntoma

| Síntoma | Comando | Referencia |
|---------|---------|------------|
| "Port already in use" | `sudo lsof -i :80` | [Debugging](#-debugging) |
| "Network not found" | `make create-network` | [Docker](#-docker) |
| "Domain not resolving" | `nslookup site.mlorentedev.test` | [DNS](#-dns-y-dominios) |
| "Container not starting" | `docker logs container_name` | [Debugging](#-debugging) |
| "Build failing" | `gh run view <run-id> --log` | [CI/CD](#-cicd) |
| "SSL certificate error" | `curl -vvI https://domain.com` | [DNS](#-dns-y-dominios) |

### Por tarea

| Tarea | Comando | Tiempo estimado |
|-------|---------|----------------|
| Setup completo local | `make env-setup && make up` | 5-10 min |
| Deploy a staging | `make deploy ENV=staging` | 2-3 min |
| Rollback producción | `make emergency-rollback ENV=production` | 1 min |
| Ver logs aplicación | `make logs APP=api` | Inmediato |
| Limpiar Docker | `docker system prune -af` | 1-2 min |

---

## 🤖 Automation

### Política general

- Todas las salidas se generan en `docs/AUTOMATION/`  
- Subcarpetas: `reports/`, `indexes/`, `changelogs/`, `adrs/`, `digests/`, `security/`  
- Una tarea → un output (archivo o diff).  
- Los PRs se hacen siempre manualmente.  
- Usar Conventional Commits (`docs:`, `chore:`, `fix:`, `ci:`, `feat:`).  
- Idempotencia: sin cambios, diff vacío.  

### Tareas comunes

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

### Auditorías

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

### Scripts de mantenimiento

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

### Seguridad

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

### Resúmenes y ADRs

```bash
# Weekly Ops Digest
Task: Summarize weekly ops (PRs, issues, docs, next steps).
Output: docs/AUTOMATION/digests/ops-digest-YYYY-WW.md

# ADRs
Task: Create ADR with context, decision, consequences.
Output: docs/AUTOMATION/adrs/ADR-<n>-<slug>.md
```

---

*💡 **Tip**: Marca esta página en tu navegador para acceso rápido durante desarrollo y operaciones.*
