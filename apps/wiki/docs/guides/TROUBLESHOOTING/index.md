# Resolución de Problemas

## Resumen

Esta guía proporciona soluciones a problemas comunes que pueden surgir durante el desarrollo local, la integración continua, y el despliegue del ecosistema mlorente.dev.

## Problemas de CI/CD

### Fallos en GitHub Actions

#### Error: "Version mismatch detected"

```bash
Error: Version mismatch detected!
Expected base version: 1.2.0
Found conflicting version: 1.3.0
```

**Causa:** Las aplicaciones tienen diferentes versiones base en el mismo release.

**Solución:**
1. Verificar que todos los commits sigan conventional commits
2. Asegurarse de que las aplicaciones modificadas tengan la misma versión base
3. Si es necesario, crear un nuevo tag manualmente:

```bash
# Forzar la creación de un tag con la versión correcta
git tag v1.2.0-rc.1
git push origin v1.2.0-rc.1
```

#### Error: "App directory does not exist"

```bash
::error::App directory apps/newapp does not exist
```

**Causa:** La aplicación especificada no tiene el directorio correspondiente.

**Solución:**
1. Verificar que el directorio `apps/[app-name]` existe
2. Comprobar que contiene un `Dockerfile` válido
3. Actualizar los filtros de rutas en `ci-01-dispatch.yml` si es una nueva aplicación

#### Fallo en construcción multi-arquitectura

```bash
ERROR: failed to solve: process "/bin/sh -c apk add --no-cache..." didn't complete successfully
```

**Causa:** Problemas de compatibilidad entre `linux/amd64` y `linux/arm64`.

**Solución:**
```dockerfile
# En lugar de comandos específicos de arquitectura
RUN apk add --no-cache package-name

# Usar comandos compatibles multi-arch
RUN apk add --no-cache --update package-name
```

**Prueba local:**
```bash
# Crear builder multi-arch
docker buildx create --use --name multiarch

# Probar construcción local
docker buildx build --platform linux/amd64,linux/arm64 .
```

### Problemas de Webhooks

#### Error: "Webhook notification failed"

```bash
::warning::Webhook URL or token not configured, skipping notification
```

**Causa:** Variables de entorno de webhook no configuradas.

**Solución:**
1. Configurar secrets en GitHub:
   - `N8N_WEBHOOK_URL`
   - `N8N_DEPLOY_TOKEN`

2. Verificar conectividad:
```bash
# Probar webhook manualmente
curl -X POST "$N8N_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $N8N_DEPLOY_TOKEN" \
  -d '{"test": true}'
```

#### Timeout en notificaciones

**Causa:** El endpoint de webhook tarda demasiado en responder.

**Solución:**
1. Aumentar el timeout en el workflow:
```bash
--max-time 60  # Aumentar de 30 a 60 segundos
```

2. Implementar retry con backoff:
```bash
for i in {1..3}; do
  if curl ...; then break; fi
  sleep $((i * 2))
done
```

## Problemas de Desarrollo Local

### Docker y Docker Compose

#### Error: "Network mlorente_net not found"

**Causa:** La red Docker requerida no existe.

**Solución:**
```bash
# Crear la red manualmente
make create-network

# O directamente:
docker network create mlorente_net
```

#### Puertos ocupados

```bash
Error starting userland proxy: listen tcp 0.0.0.0:8080: bind: address already in use
```

**Solución:**
1. Identificar procesos usando el puerto:
```bash
lsof -i :8080
netstat -tulpn | grep :8080
```

2. Terminar el proceso conflictivo:
```bash
kill -9 <PID>
```

3. O cambiar el puerto en `.env`:
```bash
TRAEFIK_DASHBOARD_PORT=8081
```

#### Problemas de permisos en volúmenes

**Causa:** Diferencias de UID/GID entre host y contenedor.

**Solución:**
```bash
# Verificar permisos actuales
ls -la apps/*/

# Ajustar permisos
sudo chown -R $USER:$USER apps/

# O usar user mapping en docker-compose
user: "${UID}:${GID}"
```

### Problemas específicos por aplicación

#### Blog (Jekyll)

**Error: "Could not find gem 'xyz'"**

**Solución:**
```bash
# Reconstruir las gemas
cd apps/blog/jekyll-site
rm Gemfile.lock
bundle install

# O desde la raíz del proyecto
make up-blog --force-recreate
```

**Error de encoding UTF-8:**

**Solución:**
```bash
# Configurar variables de entorno
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# O añadir al .env
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
```

#### API (Go)

**Error: "go: module not found"**

**Solución:**
```bash
cd apps/api/src
go mod tidy
go mod download

# Verificar conectividad a proxy.golang.org
go env GOPROXY
```

**Error de compilación con CGO:**

**Solución:**
```bash
# Deshabilitar CGO si no es necesario
export CGO_ENABLED=0

# O instalar build-essential en el contenedor
RUN apk add --no-cache gcc musl-dev
```

#### Web (Astro)

**Error: "Module not found"**

**Solución:**
```bash
cd apps/web/astro-site
rm -rf node_modules package-lock.json
npm install

# Verificar versiones
node --version  # Debe ser 20+
npm --version   # Debe ser 10+
```

**Error de memoria en construcción:**

**Solución:**
```bash
# Aumentar memoria para Node.js
export NODE_OPTIONS="--max-old-space-size=4096"

# O en docker-compose:
environment:
  - NODE_OPTIONS=--max-old-space-size=4096
```

### Problemas de DNS y conectividad

#### Dominios locales no resuelven

**Problema:** `site.mlorentedev.test` no carga.

**Solución:**

1. **Verificar /etc/hosts:**
```bash
# Añadir entradas manualmente
echo "127.0.0.1 site.mlorentedev.test" | sudo tee -a /etc/hosts
echo "127.0.0.1 blog.mlorentedev.test" | sudo tee -a /etc/hosts
echo "127.0.0.1 api.mlorentedev.test" | sudo tee -a /etc/hosts
echo "127.0.0.1 traefik.mlorentedev.test" | sudo tee -a /etc/hosts
```

2. **Usar dnsmasq (recomendado):**
```bash
# Ubuntu/Debian
sudo apt install dnsmasq
echo "address=/.mlorentedev.test/127.0.0.1" | sudo tee /etc/dnsmasq.d/mlorente

# macOS
brew install dnsmasq
echo "address=/.mlorentedev.test/127.0.0.1" | sudo tee /usr/local/etc/dnsmasq.d/mlorente
```

3. **Verificar conectividad:**
```bash
# Probar resolución DNS
nslookup site.mlorentedev.test
ping site.mlorentedev.test

# Probar conectividad HTTP
curl -H "Host: site.mlorentedev.test" http://localhost
```

### Problemas de Traefik

#### Dashboard no accesible

**Solución:**
```bash
# Verificar estado del contenedor
docker ps | grep traefik

# Revisar logs
docker logs traefik_container

# Verificar configuración
docker exec traefik_container cat /etc/traefik/traefik.yml
```

#### SSL/TLS errors

**Problema:** Certificados inválidos en desarrollo.

**Solución:**
```bash
# Regenerar certificados locales
make generate-certificates

# O usar mkcert para certificados de confianza
mkcert -install
mkcert "*.mlorentedev.test"
```

#### Routing no funciona

**Solución:**
1. Verificar labels en docker-compose:
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.web.rule=Host(`site.mlorentedev.test`)"
  - "traefik.http.routers.web.entrypoints=websecure"
```

2. Verificar red Docker:
```bash
docker network ls
docker network inspect mlorente_net
```

## Problemas de Despliegue

### Ansible

#### Error: "Host key verification failed"

**Solución:**
```bash
# Añadir host key manualmente
ssh-keyscan -H your-server.com >> ~/.ssh/known_hosts

# O deshabilitar verificación (no recomendado para producción)
export ANSIBLE_HOST_KEY_CHECKING=False
```

#### Error: "Permission denied (publickey)"

**Solución:**
```bash
# Verificar clave SSH
ssh -i ~/.ssh/your-key user@server

# Añadir clave al ssh-agent
ssh-add ~/.ssh/your-key

# Verificar configuración Ansible
ansible-inventory -i infra/ansible/inventories/production/hosts --list
```

#### Playbook falla en tareas Docker

**Causa:** Docker no está instalado o el usuario no tiene permisos.

**Solución:**
```bash
# Ejecutar bootstrap primero
make setup ENV=production SSH_HOST=user@server

# Verificar instalación Docker remota
ansible production -m command -a "docker --version"

# Verificar permisos de usuario
ansible production -m command -a "groups $USER"
```

### Problemas específicos de producción

#### Contenedores no inician

**Solución:**
```bash
# Verificar logs remotos
make logs ENV=production

# Estado de contenedores
make status ENV=production

# Reiniciar servicios específicos
make restart SERVICE=web ENV=production
```

#### Problemas de memoria

**Síntomas:** Contenedores se terminan inesperadamente.

**Solución:**
```bash
# Verificar uso de memoria
free -h
docker stats

# Aumentar límites en docker-compose
deploy:
  resources:
    limits:
      memory: 512M
    reservations:
      memory: 256M
```

#### Problemas de almacenamiento

**Causa:** Disco lleno por logs o imágenes Docker.

**Solución:**
```bash
# Limpiar logs Docker
sudo sh -c 'echo > $(docker inspect --format="{{.LogPath}}" container_name)'

# Limpiar imágenes no utilizadas
docker system prune -af --volumes

# Rotar logs con logrotate
sudo nano /etc/logrotate.d/docker
```

## Herramientas de diagnóstico

### Scripts útiles

**Verificación completa del entorno:**
```bash
#!/bin/bash
# scripts/health-check.sh

echo "=== Verificando dependencias ==="
make check

echo "=== Estado Docker ==="
docker ps -a

echo "=== Estado de redes ==="
docker network ls

echo "=== Uso de puertos ==="
netstat -tulpn | grep -E "(8080|4321|4000)"

echo "=== Variables de entorno ==="
env | grep -E "(DOMAIN|PORT|ENV)" | sort
```

**Diagnóstico de conectividad:**
```bash
#!/bin/bash
# scripts/connectivity-test.sh

DOMAINS=("site.mlorentedev.test" "blog.mlorentedev.test" "api.mlorentedev.test")

for domain in "${DOMAINS[@]}"; do
  echo "Testing $domain..."
  
  # DNS resolution
  if nslookup "$domain" > /dev/null 2>&1; then
    echo "  ✅ DNS OK"
  else
    echo "  ❌ DNS FAIL"
  fi
  
  # HTTP connectivity
  if curl -s -o /dev/null -w "%{http_code}" "http://$domain" | grep -q "200\|301\|302"; then
    echo "  ✅ HTTP OK"
  else
    echo "  ❌ HTTP FAIL"
  fi
done
```

### Comandos de depuración frecuentes

```bash
# Verificar estado general
make check && make status

# Logs en tiempo real de todos los servicios
make logs

# Reconstruir completamente el entorno
make down && make up --force-recreate

# Limpiar todo y empezar de nuevo
docker system prune -af --volumes
make up

# Verificar configuración de Traefik
docker exec -it $(docker ps -q -f name=traefik) cat /etc/traefik/traefik.yml

# Probar conectividad interna entre contenedores
docker exec -it container1 ping container2
docker exec -it container1 wget -qO- http://container2:port
```

### Monitorización y logs

**Configurar logrotate para producción:**
```bash
# /etc/logrotate.d/mlorente-docker
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    size=10M
    missingok
    delaycompress
    copytruncate
}
```

**Configurar alertas básicas:**
```bash
#!/bin/bash
# scripts/monitor.sh

# Verificar que los contenedores estén corriendo
containers=("traefik" "web" "blog" "api")

for container in "${containers[@]}"; do
  if ! docker ps | grep -q "$container"; then
    echo "ALERT: Container $container is not running"
    # Enviar notificación (webhook, email, etc.)
  fi
done
```

## Análisis de logs

### Logs de acceso de Traefik

```bash
# Ver solicitudes recientes
docker logs traefik_container_name | tail -100

# Filtrar por errores
docker logs traefik_container_name | grep -E "(4[0-9]{2}|5[0-9]{2})"

# Monitorizar en tiempo real
docker logs -f traefik_container_name
```

### Logs de aplicaciones

```bash
# Logs de API
docker logs api_container_name | grep -i error

# Logs de construcción (durante CI)
# Consultar logs de GitHub Actions para salida detallada
```

## Endpoints de verificación de salud

Una vez desplegado, estos endpoints ayudan a verificar el estado del sistema:

```bash
# Salud de la API
curl https://api.mlorente.dev/health

# Aplicación web
curl -I https://mlorente.dev

# Blog
curl -I https://blog.mlorente.dev

# Dashboard de Traefik (si está habilitado)
curl -I https://traefik.mlorente.dev/dashboard/
```

## Comandos de depuración rápida

### Verificación de estado general

```bash
# Estado general del sistema
make status

# Logs individuales de servicios
docker logs traefik_container_name
docker logs blog_container_name
docker logs api_container_name
docker logs web_container_name
```

### Depuración de red

```bash
# Verificar redes Docker
docker network ls
docker network inspect mlorente_net

# Probar conectividad entre contenedores
docker exec -it web_container_name ping api
docker exec -it api_container_name curl http://blog:4000
```

### Depuración de certificados

```bash
# Verificar expiración de certificados
echo | openssl s_client -connect mlorente.dev:443 2>/dev/null | openssl x509 -noout -dates

# Probar configuración SSL
curl -vvI https://mlorente.dev 2>&1 | grep -E "(SSL|TLS|certificate)"
```

### Depuración de CI/CD

```bash
# Verificar ejecuciones recientes de CI
gh run list --limit 10

# Ver logs de ejecución específica
gh run view <run-id> --log

# Verificar estado de workflows
gh workflow list
```

## Cuándo buscar ayuda adicional

Contactar con el mantenedor si:
1. Los problemas persisten después de probar las soluciones anteriores
2. Se descubren problemas relacionados con seguridad
3. Se necesitan cambios en la infraestructura
4. Surgen nuevos patrones de errores

## Recursos externos útiles

- [Resolución de problemas de Docker](https://docs.docker.com/engine/troubleshooting/)
- [Documentación de Traefik](https://doc.traefik.io/traefik/)
- [Resolución de problemas de Ansible](https://docs.ansible.com/ansible/latest/user_guide/playbooks_debugger.html)
- [Depuración de GitHub Actions](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows)

---

*Mantén este documento actualizado a medida que se descubran nuevos problemas y soluciones.*