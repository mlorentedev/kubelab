# Stack de Monitoreo

<div align="center">

![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat&logo=grafana&logoColor=white)
![Loki](https://img.shields.io/badge/Loki-F46800?style=flat&logo=grafana&logoColor=white)
![Vector](https://img.shields.io/badge/Vector-02C39A?style=flat&logo=vector&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

</div>

Solución integral de monitoreo y observabilidad utilizando Grafana, Loki, Vector y Uptime Kuma para métricas del sistema, agregación de logs y monitoreo de disponibilidad.

## 🏗️ Arquitectura

- **Visualización**: Grafana OSS para dashboards y alertas
- **Almacenamiento de Logs**: Loki para agregación centralizada de logs
- **Recopilación de Logs**: Vector para procesamiento y enrutamiento eficiente de logs
- **Monitoreo de Disponibilidad**: Uptime Kuma para seguimiento de disponibilidad de servicios
- **Despliegue**: Docker Compose con red proxy externa

## 📁 Estructura del Proyecto

```
apps/monitoring/
├── README.md              # Esta documentación
├── docker-compose.yml     # Stack multi-servicio de monitoreo
├── vector.toml            # Configuración de recopilación de logs de Vector
├── .env                   # Variables de entorno (no en repositorio)
└── .env.example           # Plantilla de variables de entorno
```

## 🚀 Servicios Incluidos

### Grafana OSS
- **Puerto**: 3000
- **Función**: Visualización de datos y dashboards
- **Características**:
  - Dashboards interactivos
  - Sistema de alertas
  - Soporte para múltiples fuentes de datos
  - Plugins y extensiones
  - Gestión de usuarios y equipos

### Loki
- **Puerto**: 3100
- **Función**: Almacenamiento y consulta de logs
- **Características**:
  - Agregación de logs multi-tenant
  - Consultas eficientes con LogQL
  - Retención configurable de logs
  - Compresión y indexación optimizada
  - Integración nativa con Grafana

### Vector
- **Puerto**: 8686 (API)
- **Función**: Recopilación, transformación y enrutamiento de logs
- **Características**:
  - Recopilación de logs de múltiples fuentes
  - Transformaciones en tiempo real
  - Enrutamiento basado en condiciones
  - Buffers y reintentos
  - Métricas de observabilidad integradas

### Uptime Kuma
- **Puerto**: 8000
- **Función**: Monitoreo de disponibilidad de servicios
- **Características**:
  - Verificaciones HTTP/HTTPS/TCP/DNS
  - Notificaciones multi-canal
  - Páginas de estado públicas
  - Monitoreo de SSL/certificados
  - Dashboard visual de disponibilidad

## 🔧 Configuración

### Variables de Entorno

```bash
# Configuración de Grafana
GF_SECURITY_ADMIN_PASSWORD=tu_password_aqui
GF_USERS_ALLOW_SIGN_UP=false
GF_SECURITY_ALLOW_EMBEDDING=true

# Configuración de Loki
LOKI_AUTH_ENABLED=false
LOKI_RETENTION_PERIOD=744h  # 31 días

# Configuración de Vector
VECTOR_LOG_LEVEL=info
VECTOR_API_ENABLED=true

# Configuración de Uptime Kuma
UPTIME_KUMA_DISABLE_FRAME_SAMEORIGIN=false

# Configuración de Red
MONITORING_NETWORK=proxy
```

### Configuración de Vector (`vector.toml`)

```toml
[api]
enabled = true
address = "0.0.0.0:8686"

# Fuentes de datos
[sources.docker_logs]
type = "docker_logs"
include_images = ["mlorente-*"]

[sources.system_logs]
type = "journald"
units = ["docker", "nginx", "ssh"]

# Transformaciones
[transforms.parse_logs]
type = "remap"
inputs = ["docker_logs"]
source = '''
  parsed = parse_json!(.message)
  .timestamp = parsed.timestamp
  .level = parsed.level
  .service = parsed.service
'''

# Destinos
[sinks.loki]
type = "loki"
inputs = ["parse_logs", "system_logs"]
endpoint = "http://loki:3100"
labels.job = "{{ source_type }}"
labels.service = "{{ service }}"
```

## 🐳 Despliegue

### Desarrollo Local
```bash
# Iniciar stack completo de monitoreo
docker-compose up -d

# Verificar estado de servicios
docker-compose ps

# Ver logs de servicios
docker-compose logs -f grafana
docker-compose logs -f loki
docker-compose logs -f vector
```

### Acceso a Servicios
- **Grafana**: http://localhost:3000 (admin/tu_password)
- **Loki**: http://localhost:3100/ready
- **Vector API**: http://localhost:8686/health
- **Uptime Kuma**: http://localhost:8000

### Configuración con Traefik
```yaml
# En entorno con Traefik
services:
  grafana:
    labels:
      - "traefik.http.routers.grafana.rule=Host(`grafana.mlorentedev.test`)"
      - "traefik.http.services.grafana.loadbalancer.server.port=3000"
  
  uptime-kuma:
    labels:
      - "traefik.http.routers.uptime.rule=Host(`status.mlorentedev.test`)"
      - "traefik.http.services.uptime.loadbalancer.server.port=8000"
```

## 📊 Configuración de Dashboards

### Dashboard de Sistema
```json
{
  "dashboard": {
    "title": "Sistema - Visión General",
    "panels": [
      {
        "title": "CPU Usage",
        "targets": [
          {
            "expr": "100 - (avg by (instance) (irate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)"
          }
        ]
      },
      {
        "title": "Memory Usage",
        "targets": [
          {
            "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100"
          }
        ]
      }
    ]
  }
}
```

### Dashboard de Aplicación
```json
{
  "dashboard": {
    "title": "Aplicaciones - Logs y Métricas",
    "panels": [
      {
        "title": "Logs por Servicio",
        "targets": [
          {
            "expr": "sum by (service) (rate({job=\"docker_logs\"}[5m]))"
          }
        ]
      },
      {
        "title": "Errores por Minuto",
        "targets": [
          {
            "expr": "sum by (service) (rate({level=\"error\"}[1m]))"
          }
        ]
      }
    ]
  }
}
```

## 🔍 Consultas y Alertas

### Consultas LogQL Útiles

```logql
# Logs de errores en los últimos 5 minutos
{job="docker_logs"} |= "ERROR" | json | __error__ = ""

# Logs de una aplicación específica
{service="api"} | json | level="info"

# Tasa de errores por minuto
sum by (service) (rate({level="error"}[1m]))

# Logs que contienen patrones específicos
{job="docker_logs"} |~ "failed|error|exception" | json
```

### Configuración de Alertas

```yaml
# grafana/provisioning/alerting/rules.yml
groups:
  - name: aplicaciones
    rules:
      - alert: AltaTaskDeError
        expr: sum by (service) (rate({level="error"}[5m])) > 0.1
        for: 2m
        annotations:
          summary: "Alta tasa de errores en {{ $labels.service }}"
          description: "El servicio {{ $labels.service }} tiene {{ $value }} errores por segundo"
      
      - alert: ServicioNoDisponible
        expr: up{job="aplicacion"} == 0
        for: 1m
        annotations:
          summary: "Servicio {{ $labels.instance }} no disponible"
```

## 🛠️ Mantenimiento

### Limpieza de Logs
```bash
# Limpiar logs antiguos de Loki
curl -X POST "http://localhost:3100/loki/api/v1/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{job=\"old_job\"}",
    "start": "2024-01-01T00:00:00Z",
    "end": "2024-01-31T23:59:59Z"
  }'

# Verificar uso de almacenamiento
docker system df
docker volume ls
```

### Backup de Configuraciones
```bash
# Backup de dashboards de Grafana
mkdir -p backups/grafana
docker cp $(docker-compose ps -q grafana):/var/lib/grafana/dashboards ./backups/grafana/

# Backup de configuración de Vector
cp vector.toml backups/vector-$(date +%Y%m%d).toml
```

## 📈 Métricas y KPIs

### Métricas de Sistema
- **CPU**: Utilización por core y promedio
- **Memoria**: Uso, disponible y swap
- **Disco**: Espacio usado, IOPS, latencia
- **Red**: Tráfico entrante/saliente, errores

### Métricas de Aplicación
- **Disponibilidad**: Uptime de servicios
- **Rendimiento**: Tiempo de respuesta, throughput
- **Errores**: Tasa de errores, tipos de errores
- **Logs**: Volumen de logs, niveles de severidad

### Alertas Críticas
- Servicios no disponibles (> 1 minuto)
- Uso de CPU > 80% (> 5 minutos)
- Uso de memoria > 90% (> 2 minutos)
- Espacio en disco < 10% disponible
- Tasa de errores > 5% (> 2 minutos)

## 🔗 Integración con Otras Herramientas

### Notificaciones
- **Slack**: Canales de alertas por severidad
- **Email**: Notificaciones para admins
- **Webhook**: Integración con sistemas de tickets
- **Discord**: Notificaciones para equipo de desarrollo

### Fuentes de Datos Adicionales
- **Prometheus**: Métricas de aplicaciones
- **Node Exporter**: Métricas de sistema
- **cAdvisor**: Métricas de contenedores
- **Blackbox Exporter**: Monitoreo de endpoints

## 🤝 Contribuir

1. Añadir nuevas fuentes de datos a Vector
2. Crear dashboards específicos por servicio
3. Configurar alertas apropiadas por criticidad
4. Documentar consultas LogQL útiles
5. Optimizar retención y almacenamiento de logs

## 🔗 Servicios Relacionados

- **Web Frontend**: `apps/web` - Métricas de sitio web
- **API Backend**: `apps/api` - Logs y métricas de API
- **Blog**: `apps/blog` - Monitoreo de contenido estático
- **Infraestructura**: `infra/traefik` - Métricas de proxy reverso