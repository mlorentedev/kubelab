# Guía Avanzada de Despliegue

## Resumen

Esta guía cubre escenarios avanzados de despliegue, configuración de servidor y procedimientos operacionales que van más allá del flujo básico `make deploy` descrito en el README principal.

## Requisitos del Servidor

### Especificaciones Mínimas de Hardware

| Entorno | CPU | RAM | Almacenamiento | Red |
|---------|-----|-----|----------------|-----|
| **Staging** | 1 vCPU | 2GB | 20GB SSD | 1Gbps |
| **Producción** | 2 vCPU | 4GB | 40GB SSD | 1Gbps |
| **Alto tráfico** | 4 vCPU | 8GB | 80GB SSD | 1Gbps |

### Requisitos del Sistema Operativo

**Compatibles:**
- Ubuntu 22.04 LTS ✅ (Recomendado)
- Ubuntu 20.04 LTS ✅
- Debian 11/12 ✅
- CentOS Stream 9 ⚠️ (Pruebas limitadas)

**Software Requerido:**
```bash
# Instalado automáticamente por el playbook de configuración
- Docker Engine 24+
- Docker Compose v2.20+
- Python 3.8+ (para Ansible)
- Git 2.0+
- Curl, wget, unzip
```

### Configuración de Red

**Puertos Requeridos:**
```bash
# Entrantes
80/tcp    # HTTP (redirige a HTTPS)
443/tcp   # HTTPS (todas las aplicaciones)
22/tcp    # SSH (para despliegue)

# Opcionales (para monitorización/gestión)
8080/tcp  # Dashboard de Traefik (si está habilitado)
9090/tcp  # Prometheus (si está expuesto)
3000/tcp  # Grafana (si está expuesto)
```

**Requisitos DNS:**
```bash
# Registros A apuntando a la IP del servidor
mlorente.dev           -> IP_DEL_SERVIDOR
blog.mlorente.dev      -> IP_DEL_SERVIDOR
api.mlorente.dev       -> IP_DEL_SERVIDOR
traefik.mlorente.dev   -> IP_DEL_SERVIDOR (opcional)
```

## Configuración Inicial del Servidor

### 1. Configuración de Usuario

Crear usuario dedicado para despliegue:
```bash
# Ejecutar en el servidor como root
adduser mlorente-deployer
usermod -aG docker mlorente-deployer
usermod -aG sudo mlorente-deployer

# Configurar sudo sin contraseña
echo "mlorente-deployer ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/mlorente-deployer
```

### 2. Configuración de Claves SSH

```bash
# En tu máquina local
ssh-keygen -t ed25519 -C "mlorente-deployer@mlorente.dev" -f ~/.ssh/mlorente-deploy

# Copiar al servidor
ssh-copy-id -i ~/.ssh/mlorente-deploy.pub mlorente-deployer@IP_DEL_SERVIDOR

# Probar conexión
ssh -i ~/.ssh/mlorente-deploy mlorente-deployer@IP_DEL_SERVIDOR
```

### 3. Configuración del Cortafuegos

```bash
# Ubuntu UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# CentOS/RHEL Firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

## Configuraciones Específicas por Entorno

### Entorno de Staging

**Configuración de Inventario:**
```yaml
# infra/ansible/inventories/hosts.yml
staging:
  hosts:
    staging-server:
      ansible_host: staging.mlorente.dev
      ansible_user: mlorente-deployer
      ansible_ssh_private_key_file: ~/.ssh/mlorente-deploy
  vars:
    env: staging
    domain: staging.mlorente.dev
    deploy_path: /opt/mlorente-staging
    letsencrypt_staging: true  # Usar certificados de prueba
```

**Variables Específicas de Staging:**
```yaml
# infra/ansible/inventories/group_vars/staging.yml
# Límites de recursos para staging
docker_memory_limit: 512m
docker_cpu_limit: "0.5"

# Niveles de log reducidos
log_level: warn

# Deshabilitar algunos componentes de monitorización
monitoring_enabled: false
```

### Entorno de Producción

**Configuración de Inventario:**
```yaml
# infra/ansible/inventories/hosts.yml
production:
  hosts:
    prod-server:
      ansible_host: mlorente.dev
      ansible_user: mlorente-deployer
      ansible_ssh_private_key_file: ~/.ssh/mlorente-deploy
  vars:
    env: production
    domain: mlorente.dev
    deploy_path: /opt/mlorente-prod
    letsencrypt_staging: false  # Usar certificados de producción
```

**Variables Específicas de Producción:**
```yaml
# infra/ansible/inventories/group_vars/production.yml
# Asignación completa de recursos
docker_memory_limit: 2g
docker_cpu_limit: "1.0"

# Monitorización mejorada
monitoring_enabled: true
log_level: info

# Configuración de copias de seguridad
backup_enabled: true
backup_retention_days: 30
```

## Flujos de Trabajo de Despliegue

### Proceso de Despliegue Estándar

```bash
# 1. Descargar y extraer el bundle de release
wget https://github.com/mlorentedev/mlorente.dev/releases/download/v1.2.0/global-release-v1.2.0.zip
unzip global-release-v1.2.0.zip

# 2. Revisar VERSION_MANIFEST.md para ver cambios
cat deployment/VERSION_MANIFEST.md

# 3. Desplegar primero a staging
make deploy ENV=staging RELEASE_VERSION=v1.2.0

# 4. Validar despliegue en staging
make status ENV=staging
curl -I https://staging.mlorente.dev

# 5. Desplegar a producción
make deploy ENV=production RELEASE_VERSION=v1.2.0
```

### Despliegue Sin Tiempo de Inactividad

Usando patrón de despliegue blue-green:

```bash
# 1. Desplegar al entorno de staging (verde)
make deploy ENV=staging RELEASE_VERSION=v1.2.0

# 2. Ejecutar pruebas de humo en staging
curl -f https://staging.mlorente.dev/health || exit 1
curl -f https://api.staging.mlorente.dev/health || exit 1

# 3. Cambiar tráfico de producción (actualización atómica)
make deploy ENV=production RELEASE_VERSION=v1.2.0

# 4. Monitorizar por problemas
tail -f /opt/mlorente-prod/logs/traefik.log
```

### Procedimientos de Rollback

**Rollback Rápido:**
```bash
# Rollback a versión anterior
make deploy ENV=production RELEASE_VERSION=v1.1.0

# Rollback de emergencia (usa versión predefinida)
make emergency-rollback ENV=production
```

**Pasos de Rollback Manual:**
```bash
# 1. Identificar última versión conocida como buena
git tag --sort=-version:refname | grep -v "rc\|alpha\|beta" | head -5

# 2. Desplegar versión específica
make deploy ENV=production RELEASE_VERSION=v1.1.0

# 3. Verificar éxito del rollback
curl -I https://mlorente.dev
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

# 4. Documentar incidente
echo "Rollback completado en $(date): v1.2.0 -> v1.1.0" >> /var/log/deployments.log
```

## Gestión de Secretos

### Variables de Entorno

**Secretos Requeridos por Entorno:**
```bash
# Producción
DOCKERHUB_USERNAME=tu-usuario
DOCKERHUB_TOKEN=tu-token
N8N_WEBHOOK_URL=https://n8n.mlorente.dev/webhook/deploy
N8N_DEPLOY_TOKEN=token-webhook-seguro
LETSENCRYPT_EMAIL=admin@mlorente.dev

# Staging (misma estructura, valores diferentes)
N8N_WEBHOOK_URL=https://n8n-staging.mlorente.dev/webhook/deploy
```

### Distribución de Secretos

**Usando Ansible Vault:**
```bash
# Crear archivo de variables cifrado
ansible-vault create infra/ansible/inventories/group_vars/production/vault.yml

# Editar variables cifradas
ansible-vault edit infra/ansible/inventories/group_vars/production/vault.yml

# Desplegar con contraseña de vault
make deploy ENV=production --ask-vault-pass
```

**Plantilla de Archivo de Entorno:**
```bash
# Generar archivos .env para cada entorno
scripts/create-env-example.sh production
scripts/create-env-example.sh staging
```

## Monitorización y Verificaciones de Salud

### Endpoints de Salud de Aplicaciones

```bash
# Verificaciones automáticas de salud durante despliegue
check_health() {
  local env=$1
  local domain
  
  case $env in
    staging) domain="staging.mlorente.dev" ;;
    production) domain="mlorente.dev" ;;
  esac
  
  # Verificar todos los endpoints críticos
  curl -f "https://${domain}" || return 1
  curl -f "https://blog.${domain}" || return 1
  curl -f "https://api.${domain}/health" || return 1
  
  echo "✅ Todas las verificaciones de salud pasaron para $env"
}

# Uso
check_health production
```

### Monitorización de Rendimiento

**Monitorización de Uso de Recursos:**
```bash
# Uso de recursos de contenedores
docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# Monitorización de uso de disco
df -h /opt/mlorente-*

# Estado de rotación de logs
du -sh /opt/mlorente-*/logs/
```

**Métricas de Rendimiento de Aplicaciones:**
```bash
# Monitorización de tiempo de respuesta
curl -w "@curl-format.txt" -o /dev/null -s https://mlorente.dev

# Donde curl-format.txt contiene:
     time_namelookup:  %{time_namelookup}s\n
        time_connect:  %{time_connect}s\n
     time_appconnect:  %{time_appconnect}s\n
    time_pretransfer:  %{time_pretransfer}s\n
       time_redirect:  %{time_redirect}s\n
  time_starttransfer:  %{time_starttransfer}s\n
                     ----------\n
          time_total:  %{time_total}s\n
```

## Copias de Seguridad y Recuperación ante Desastres

### Estrategia de Copias de Seguridad de Datos

**Qué hacer copias de seguridad:**
```bash
# 1. Configuraciones de aplicaciones
/opt/mlorente-*/apps/*/docker-compose.prod.yml
/opt/mlorente-*/apps/*/.env

# 2. Configuraciones y certificados de Traefik
/opt/mlorente-*/infra/traefik/
/opt/traefik/acme.json  # Certificados SSL

# 3. Datos de aplicaciones (si los hay)
/opt/mlorente-*/volumes/  # Volúmenes persistentes

# 4. Historial de despliegues
/var/log/deployments.log
```

**Script Automatizado de Copias de Seguridad:**
```bash
#!/bin/bash
# backup-mlorente.sh

ENV=${1:-production}
BACKUP_DIR="/backups/mlorente-$(date +%Y%m%d-%H%M%S)"
DEPLOY_PATH="/opt/mlorente-${ENV}"

mkdir -p "$BACKUP_DIR"

# Copiar configuraciones
tar -czf "$BACKUP_DIR/configs.tar.gz" "$DEPLOY_PATH"

# Copiar certificados (¡crítico!)
cp /opt/traefik/acme.json "$BACKUP_DIR/acme.json.bak"

# Copiar cualquier dato persistente
if [ -d "$DEPLOY_PATH/volumes" ]; then
    tar -czf "$BACKUP_DIR/volumes.tar.gz" "$DEPLOY_PATH/volumes"
fi

# Crear manifiesto
cat > "$BACKUP_DIR/backup-manifest.txt" << EOF
Copia de seguridad creada: $(date)
Entorno: $ENV
Commit de Git: $(git rev-parse HEAD)
Imágenes Docker:
$(docker images --format "{{.Repository}}:{{.Tag}}" | grep mlorente)
EOF

echo "✅ Copia de seguridad creada: $BACKUP_DIR"
```

### Procedimientos de Recuperación ante Desastres

**Recuperación Completa del Servidor:**
```bash
# 1. Provisionar nuevo servidor con las mismas especificaciones
# 2. Ejecutar configuración inicial
make setup ENV=production SSH_HOST=mlorente-deployer@IP_NUEVO_SERVIDOR

# 3. Restaurar configuraciones desde copia de seguridad
scp backup-YYYYMMDD-HHMMSS/configs.tar.gz IP_NUEVO_SERVIDOR:/tmp/
ssh IP_NUEVO_SERVIDOR "cd /opt && tar -xzf /tmp/configs.tar.gz"

# 4. Restaurar certificados SSL
scp backup-YYYYMMDD-HHMMSS/acme.json.bak IP_NUEVO_SERVIDOR:/opt/traefik/acme.json

# 5. Desplegar última versión
make deploy ENV=production RELEASE_VERSION=v1.2.0

# 6. Actualizar DNS para apuntar al nuevo servidor
# 7. Verificar que todos los servicios funcionan
```

## Endurecimiento de Seguridad

### Seguridad a Nivel de Servidor

```bash
# 1. Deshabilitar acceso SSH de root
echo "PermitRootLogin no" >> /etc/ssh/sshd_config
systemctl reload sshd

# 2. Habilitar actualizaciones de seguridad automáticas
echo 'Unattended-Upgrade::Automatic-Reboot "false";' >> /etc/apt/apt.conf.d/50unattended-upgrades
systemctl enable unattended-upgrades

# 3. Configurar fail2ban
apt install fail2ban
systemctl enable fail2ban

# 4. Seguridad del daemon Docker
echo '{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}' > /etc/docker/daemon.json
systemctl reload docker
```

### Seguridad de Aplicaciones

**Configuración SSL/TLS:**
```yaml
# Cabeceras de seguridad de Traefik (ya configuradas)
middlewares:
  security-headers:
    headers:
      customRequestHeaders:
        X-Forwarded-Proto: "https"
      customResponseHeaders:
        X-Frame-Options: "DENY"
        X-Content-Type-Options: "nosniff"
        Strict-Transport-Security: "max-age=31536000"
```

**Seguridad de Contenedores:**
```yaml
# Configuraciones de seguridad en docker compose
services:
  app:
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
```

## Optimización del Rendimiento

### Optimización de Docker

```yaml
# Optimizaciones en docker-compose.prod.yml
services:
  web:
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4321/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Rendimiento de Traefik

```yaml
# Optimizaciones en traefik.yml
log:
  level: WARN  # Reducir ruido de logs en producción
  
accessLog:
  bufferingSize: 100  # Buffer de logs de acceso
  
metrics:
  prometheus:
    addEntryPointsLabels: true
    addServicesLabels: true
```

### Optimizaciones a Nivel de Sistema

```bash
# Aumentar límites de descriptores de archivo
echo "fs.file-max = 2097152" >> /etc/sysctl.conf
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# Optimizar configuraciones de red
echo "net.core.somaxconn = 65535" >> /etc/sysctl.conf
echo "net.ipv4.tcp_max_syn_backlog = 65535" >> /etc/sysctl.conf

# Aplicar cambios
sysctl -p
```

## Procedimientos de Mantenimiento

### Tareas de Mantenimiento Regulares

**Semanales:**
```bash
# 1. Actualizar paquetes del sistema
sudo apt update && sudo apt upgrade -y

# 2. Limpiar imágenes Docker antiguas
docker system prune -f

# 3. Rotar y comprimir logs
logrotate -f /etc/logrotate.conf

# 4. Verificar espacio en disco
df -h
```

**Mensuales:**
```bash
# 1. Hacer copia de seguridad de configuración actual
./scripts/backup-mlorente.sh production

# 2. Revisar y limpiar copias de seguridad antiguas
find /backups -mtime +30 -delete

# 3. Actualizar Docker y Docker Compose
# (Seguir proceso oficial de actualización de Docker)

# 4. Verificación de salud de certificados
openssl x509 -in /opt/traefik/acme.json -text -noout | grep "Not After"
```

### Ventanas de Mantenimiento

**Proceso de Mantenimiento Programado:**
```bash
# 1. Anunciar mantenimiento (si afecta a usuarios)
# Publicar aviso en sitio/redes sociales

# 2. Habilitar modo mantenimiento (opcional)
# Redirigir tráfico a página de mantenimiento

# 3. Realizar tareas de mantenimiento
make deploy ENV=production RELEASE_VERSION=v1.3.0

# 4. Ejecutar verificaciones post-despliegue
check_health production

# 5. Deshabilitar modo mantenimiento
# Restaurar tráfico normal
```

## Escenarios Avanzados de Despliegue

### Configuración Multi-Servidor

Para despliegues de alta disponibilidad a través de múltiples servidores:

```yaml
# infra/ansible/inventories/hosts.yml
production:
  children:
    web_servers:
      hosts:
        web01:
          ansible_host: 10.0.1.10
        web02:
          ansible_host: 10.0.1.11
    api_servers:
      hosts:
        api01:
          ansible_host: 10.0.2.10
        api02:
          ansible_host: 10.0.2.11
    load_balancers:
      hosts:
        lb01:
          ansible_host: 10.0.0.10
```

### Migración a Orquestación de Contenedores

Cuando esté listo para migrar a Kubernetes:

```bash
# 1. Generar manifiestos de Kubernetes desde Docker Compose
kompose convert -f apps/web/docker-compose.prod.yml

# 2. Adaptar configuración de Traefik para Kubernetes
# Usar Traefik Ingress Controller en lugar de labels Docker

# 3. Migrar secretos a secretos de Kubernetes
kubectl create secret generic mlorente-secrets --from-env-file=.env

# 4. Desplegar aplicaciones
kubectl apply -f k8s/
```

---

*Esta guía cubre escenarios avanzados de despliegue. Para despliegue básico, consulta el README principal. Actualiza este documento cuando surjan nuevos patrones de despliegue y requisitos.*