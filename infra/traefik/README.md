# Traefik - Proxy Reverso

Proxy reverso moderno y load balancer que facilita el despliegue de microservicios con descubrimiento automático de servicios, terminación TLS y enrutamiento dinámico.

## 🏗️ Arquitectura

- **Versión**: Traefik v3.0 con soporte completo HTTP/3
- **Descubrimiento**: Automático vía Docker labels y archivos de configuración
- **TLS**: Terminación SSL/TLS automática con Let's Encrypt
- **Configuración**: Híbrida con archivos estáticos y dinámicos
- **Red**: Red Docker externa compartida para todos los servicios

## 📁 Estructura del Proyecto

```
infra/traefik/
├── README.md              # Esta documentación
├── docker-compose.yml     # Configuración del servicio Traefik
├── traefik.yml           # Configuración estática principal
├── .env                  # Variables de entorno (no en repositorio)
├── certs/                # Certificados SSL/TLS
│   └── acme.json         # Certificados Let's Encrypt
├── dynamic/              # Configuraciones dinámicas activas
│   ├── middlewares.yml   # Middlewares globales
│   ├── tls.yml          # Configuración TLS global
│   ├── app-*.yml        # Configuraciones por aplicación
│   └── nginx.yml        # Configuración servidor estático
├── templates/           # Plantillas de configuración
│   ├── *.template.yml   # Plantillas para nuevos servicios
│   └── traefik.*.template.yml # Plantillas HTTP/HTTPS
└── logs/               # Logs de acceso y error
```

## 🚀 Características

### Proxy Reverso Avanzado

- **Enrutamiento Inteligente**: Enrutamiento basado en dominio, path, headers y query params
- **Load Balancing**: Múltiples algoritmos de balanceado de carga
- **Health Checks**: Verificación de salud automática de backends
- **Circuit Breaker**: Protección contra cascading failures
- **Retry Logic**: Reintentos automáticos con backoff exponencial
- **Sticky Sessions**: Sesiones pegajosas para aplicaciones stateful

### Gestión TLS Automática

- **Let's Encrypt**: Obtención y renovación automática de certificados
- **ACME Protocol**: Soporte completo para desafíos HTTP-01 y TLS-ALPN-01
- **Wildcard Certificates**: Certificados comodín con desafío DNS-01
- **Custom CA**: Soporte para autoridades certificadoras personalizadas
- **TLS Termination**: Terminación SSL en el proxy con re-encryption opcional
- **HSTS**: HTTP Strict Transport Security automático

### Descubrimiento de Servicios

- **Docker Integration**: Descubrimiento automático vía labels Docker
- **File Provider**: Configuración vía archivos YAML/TOML
- **Consul/Etcd**: Integración con service discovery externos
- **API Provider**: Configuración vía API REST
- **Hot Reload**: Recarga de configuración sin reinicio
- **Multi-provider**: Múltiples fuentes de configuración simultáneas

### Monitoreo y Observabilidad

- **Dashboard Web**: Interfaz gráfica de administración
- **Métricas Prometheus**: Exportación nativa de métricas
- **Access Logs**: Logs de acceso detallados en múltiples formatos
- **Tracing**: Integración con Jaeger, Zipkin, DataDog
- **API REST**: API completa para gestión y monitoreo
- **Health Endpoints**: Endpoints de salud y readiness

### Middlewares Avanzados

- **Autenticación**: BasicAuth, DigestAuth, ForwardAuth, OAuth
- **Rate Limiting**: Limitación de velocidad por IP, usuario, endpoint
- **Request/Response Modification**: Transformación de headers y body
- **Compression**: Compresión Gzip automática
- **CORS**: Cross-Origin Resource Sharing configurable
- **Security Headers**: Headers de seguridad automáticos

## 🔧 Configuración

### Variables de Entorno

Crea un archivo `.env` con la siguiente configuración:

```bash
# Configuración General
TRAEFIK_DOMAIN=tudominio.com
TRAEFIK_SUBDOMAIN=traefik
TRAEFIK_EMAIL=admin@tudominio.com

# Let's Encrypt Configuration
LETS_ENCRYPT_EMAIL=letsencrypt@tudominio.com
ACME_CA_SERVER=https://acme-v02.api.letsencrypt.org/directory
# Para testing: https://acme-staging-v02.api.letsencrypt.org/directory

# Dashboard Security
TRAEFIK_DASHBOARD_AUTH=admin:$2y$10$ejemplo_hash_bcrypt

# Logging Configuration
LOG_LEVEL=INFO
ACCESS_LOG_FORMAT=json

# Network Configuration
DOCKER_NETWORK=proxy
DOCKER_SOCKET=/var/run/docker.sock

# Optional: External Provider Settings
CONSUL_ENDPOINTS=consul:8500
ETCD_ENDPOINTS=etcd:2379
```

### Configuración Estática (traefik.yml)

```yaml
# Configuración principal Traefik
api:
  dashboard: true
  debug: false

# Health check endpoint
ping: {}

# Logging configuration
log:
  level: INFO
  filePath: /logs/traefik.log

accessLog:
  filePath: /logs/access.log
  format: json

# Entry points (puertos de entrada)
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
          permanent: true

  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt

  traefik:
    address: ":8080"

# Certificate resolvers
certificatesResolvers:
  letsencrypt:
    acme:
      email: letsencrypt@tudominio.com
      storage: /letsencrypt/acme.json
      httpChallenge:
        entryPoint: web

# Service providers
providers:
  docker:
    endpoint: "unix:///var/run/docker.sock"
    exposedByDefault: false
    network: proxy
    watch: true

  file:
    directory: "/etc/traefik/dynamic"
    watch: true

# Global configuration
global:
  checkNewVersion: false
  sendAnonymousUsage: false
```

### Configuración Dinámica

#### Middlewares Globales (dynamic/middlewares.yml)

```yaml
http:
  middlewares:
    # Security headers middleware
    secure-headers:
      headers:
        accessControlAllowMethods:
          - GET
          - OPTIONS
          - PUT
          - POST
          - DELETE
        accessControlMaxAge: 100
        hostsProxyHeaders:
          - "X-Forwarded-Host"
        referrerPolicy: "same-origin"
        customRequestHeaders:
          X-Forwarded-Proto: "https"
        customResponseHeaders:
          X-Frame-Options: "DENY"
          X-Content-Type-Options: "nosniff"
          X-XSS-Protection: "1; mode=block"
          Strict-Transport-Security: "max-age=31536000; includeSubDomains"

    # Rate limiting
    rate-limit:
      rateLimit:
        burst: 100
        period: 10s

    # Basic authentication
    auth-basic:
      basicAuth:
        users:
          - "admin:$2y$10$tu_hash_bcrypt_aqui"

    # Compression
    gzip-compress:
      compress: {}

    # CORS headers
    cors-headers:
      headers:
        accessControlAllowOriginList:
          - "https://tudominio.com"
          - "https://*.tudominio.com"
        accessControlAllowHeaders:
          - "Content-Type"
          - "Authorization"
        accessControlAllowMethods:
          - "GET"
          - "POST"
          - "PUT"
          - "DELETE"
          - "OPTIONS"
```

#### Configuración TLS (dynamic/tls.yml)

```yaml
tls:
  options:
    modern:
      minVersion: "VersionTLS12"
      maxVersion: "VersionTLS13"
      cipherSuites:
        - "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
        - "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305"
        - "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256"
      curvePreferences:
        - "CurveP521"
        - "CurveP384"
      sniStrict: true

    intermediate:
      minVersion: "VersionTLS10"
      cipherSuites:
        - "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
        - "TLS_RSA_WITH_AES_256_GCM_SHA384"

  stores:
    default:
      defaultCertificate:
        certFile: /certs/default.crt
        keyFile: /certs/default.key
```

## 🐳 Despliegue Docker

### Configuración del Servicio

```yaml
services:
  traefik:
    image: traefik:v3.0
    container_name: traefik
    restart: always
    ports:
      - "80:80"     # HTTP
      - "443:443"   # HTTPS
      - "8080:8080" # Dashboard
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./traefik.yml:/etc/traefik/traefik.yml:ro"
      - "./dynamic:/etc/traefik/dynamic:ro"
      - "./certs:/certs"
      - "./logs:/logs"
    environment:
      - "TRAEFIK_LOG_LEVEL=${LOG_LEVEL:-INFO}"
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dashboard.rule=Host(`traefik.${TRAEFIK_DOMAIN}`)"
      - "traefik.http.routers.dashboard.tls=true"
      - "traefik.http.routers.dashboard.tls.certresolver=letsencrypt"
      - "traefik.http.routers.dashboard.middlewares=auth-basic@file"

networks:
  proxy:
    external: true
```

### Configuración de Red

```bash
# Crear red externa compartida
docker network create proxy

# Verificar red
docker network ls | grep proxy
docker network inspect proxy
```

### Despliegue de Desarrollo

```bash
# Crear estructura de directorios
mkdir -p certs logs dynamic templates

# Configurar permisos para certificados
touch certs/acme.json
chmod 600 certs/acme.json

# Crear archivo de entorno
cat > .env << EOF
TRAEFIK_DOMAIN=localhost
TRAEFIK_EMAIL=admin@localhost
LETS_ENCRYPT_EMAIL=test@localhost
ACME_CA_SERVER=https://acme-staging-v02.api.letsencrypt.org/directory
LOG_LEVEL=DEBUG
EOF

# Iniciar Traefik
docker-compose up -d

# Verificar logs
docker-compose logs -f traefik

# Acceder al dashboard
open http://localhost:8080
```

### Despliegue de Producción

```bash
# Configurar variables de producción
cat > .env << EOF
TRAEFIK_DOMAIN=tudominio.com
TRAEFIK_EMAIL=admin@tudominio.com
LETS_ENCRYPT_EMAIL=letsencrypt@tudominio.com
ACME_CA_SERVER=https://acme-v02.api.letsencrypt.org/directory
LOG_LEVEL=INFO
EOF

# Generar hash para autenticación básica
htpasswd -nb admin tu-contraseña-segura

# Configurar certificados
chmod 600 certs/acme.json

# Desplegar en producción
docker-compose up -d

# Monitorear despliegue
docker-compose logs -f traefik
```

## 🛠️ Configuración de Aplicaciones

### Configuración vía Docker Labels

```yaml
# Ejemplo: Aplicación web con HTTPS automático
services:
  web:
    image: nginx:alpine
    container_name: mi-web
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.web.rule=Host(`www.tudominio.com`)"
      - "traefik.http.routers.web.entrypoints=websecure"
      - "traefik.http.routers.web.tls=true"
      - "traefik.http.routers.web.tls.certresolver=letsencrypt"
      - "traefik.http.routers.web.middlewares=secure-headers@file,gzip-compress@file"
      - "traefik.http.services.web.loadbalancer.server.port=80"

networks:
  proxy:
    external: true
```

### Configuración vía Archivos

```yaml
# dynamic/app-ejemplo.yml
http:
  routers:
    app-ejemplo:
      rule: "Host(`app.tudominio.com`)"
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
      middlewares:
        - secure-headers@file
        - rate-limit@file
      service: app-ejemplo-service

  services:
    app-ejemplo-service:
      loadBalancer:
        servers:
          - url: "http://app:3000"
        healthCheck:
          path: "/health"
          interval: "30s"
          timeout: "10s"
```

### Configuración Multi-dominio

```yaml
# Múltiples dominios para la misma aplicación
labels:
  - "traefik.enable=true"
  
  # Router principal
  - "traefik.http.routers.web.rule=Host(`tudominio.com`,`www.tudominio.com`)"
  - "traefik.http.routers.web.entrypoints=websecure"
  - "traefik.http.routers.web.tls=true"
  - "traefik.http.routers.web.tls.certresolver=letsencrypt"
  
  # Redirect www a dominio principal
  - "traefik.http.middlewares.www-redirect.redirectregex.regex=^https://www\\.(.+)"
  - "traefik.http.middlewares.www-redirect.redirectregex.replacement=https://$${1}"
  - "traefik.http.middlewares.www-redirect.redirectregex.permanent=true"
  
  - "traefik.http.routers.web.middlewares=www-redirect@docker"
```

## 🔍 Monitoreo y Troubleshooting

### Dashboard Web

Accede al dashboard en: `https://traefik.tudominio.com`

El dashboard proporciona:
- Vista en tiempo real de todos los servicios
- Estado de health checks
- Métricas de tráfico
- Configuración activa
- Logs en tiempo real

### Logs y Debugging

```bash
# Ver logs en tiempo real
docker-compose logs -f traefik

# Logs con nivel DEBUG
docker-compose exec traefik traefik --log.level=DEBUG

# Verificar configuración
docker-compose exec traefik traefik config

# Verificar conectividad
docker-compose exec traefik ping -c 3 google.com

# Estado de servicios
curl -s http://localhost:8080/api/http/services | jq
curl -s http://localhost:8080/api/http/routers | jq
```

### Métricas Prometheus

```yaml
# Habilitar métricas en traefik.yml
metrics:
  prometheus:
    addEntryPointsLabels: true
    addServicesLabels: true
    buckets:
      - 0.1
      - 0.3
      - 1.2
      - 5.0

# Endpoint de métricas: http://traefik:8080/metrics
```

### Health Checks

```bash
# Health check básico
curl -f http://localhost:8080/ping

# API health
curl -f http://localhost:8080/api/version

# Verificar certificados
curl -I https://tudominio.com

# Verificar headers de seguridad
curl -I https://tudominio.com | grep -i security
```

## 🚀 Características Avanzadas

### Load Balancing Avanzado

```yaml
# Configuración de load balancing
http:
  services:
    api-loadbalancer:
      loadBalancer:
        servers:
          - url: "http://api1:3000"
          - url: "http://api2:3000"
          - url: "http://api3:3000"
        sticky:
          cookie:
            name: "traefik-sticky"
            secure: true
            httpOnly: true
        healthCheck:
          path: "/health"
          interval: "10s"
          timeout: "5s"
          retries: 3
```

### Circuit Breaker

```yaml
# Protección contra fallos en cascada
http:
  middlewares:
    circuit-breaker:
      circuitBreaker:
        expression: "NetworkErrorRatio() > 0.3 || ResponseCodeRatio(500, 600, 0, 600) > 0.3"
        checkPeriod: "10s"
        fallbackDuration: "30s"
        recoveryDuration: "10s"
```

### Rate Limiting Avanzado

```yaml
# Rate limiting por IP y usuario
http:
  middlewares:
    rate-limit-advanced:
      rateLimit:
        average: 100
        period: "60s"
        burst: 200
        sourceCriterion:
          ipStrategy:
            depth: 2
            excludedIPs:
              - "127.0.0.1/32"
              - "192.168.1.0/24"
```

### Autenticación Forward Auth

```yaml
# Autenticación externa
http:
  middlewares:
    oauth-auth:
      forwardAuth:
        address: "https://auth.tudominio.com/verify"
        authResponseHeaders:
          - "X-Auth-User"
          - "X-Auth-Groups"
        authRequestHeaders:
          - "Authorization"
        trustForwardHeader: true
```

## 🔐 Seguridad

### Certificados SSL/TLS

```bash
# Verificar certificados Let's Encrypt
docker-compose exec traefik cat /letsencrypt/acme.json | jq

# Renovación manual (normalmente automática)
docker-compose exec traefik traefik acme renew

# Backup de certificados
cp certs/acme.json certs/acme.json.backup.$(date +%Y%m%d)
```

### Hardening de Seguridad

```yaml
# Configuración segura en traefik.yml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

api:
  dashboard: true
  insecure: false

# Headers de seguridad globales
http:
  middlewares:
    security-headers:
      headers:
        frameDeny: true
        contentTypeNosniff: true
        browserXssFilter: true
        referrerPolicy: "strict-origin-when-cross-origin"
        customRequestHeaders:
          X-Forwarded-Proto: "https"
        customResponseHeaders:
          Strict-Transport-Security: "max-age=31536000; includeSubDomains; preload"
          Content-Security-Policy: "default-src 'self'; script-src 'self' 'unsafe-inline'"
```

### Firewall y Restricciones

```yaml
# Restricción por IP
http:
  middlewares:
    ip-whitelist:
      ipWhiteList:
        sourceRange:
          - "127.0.0.1/32"
          - "192.168.1.0/24"
          - "10.0.0.0/8"

    # Bloquear IPs específicas
    ip-blacklist:
      ipWhiteList:
        sourceRange:
          - "0.0.0.0/0"
        excludedIPs:
          - "192.168.1.100/32"
          - "10.0.0.50/32"
```

## 🔧 Plantillas y Automatización

### Plantillas de Configuración

```yaml
# templates/app-template.yml
http:
  routers:
    {{.ServiceName}}:
      rule: "Host(`{{.Domain}}`)"
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
      middlewares:
        - secure-headers@file
        - gzip-compress@file
      service: {{.ServiceName}}-service

  services:
    {{.ServiceName}}-service:
      loadBalancer:
        servers:
          - url: "http://{{.ServiceName}}:{{.Port}}"
        healthCheck:
          path: "/health"
          interval: "30s"
```

### Script de Despliegue

```bash
#!/bin/bash
# deploy-app.sh

APP_NAME=$1
DOMAIN=$2
PORT=${3:-3000}

if [[ -z "$APP_NAME" || -z "$DOMAIN" ]]; then
    echo "Uso: $0 <app-name> <domain> [port]"
    exit 1
fi

# Generar configuración desde plantilla
sed "s/{{.ServiceName}}/$APP_NAME/g; s/{{.Domain}}/$DOMAIN/g; s/{{.Port}}/$PORT/g" \
    templates/app-template.yml > dynamic/app-$APP_NAME.yml

echo "Configuración creada para $APP_NAME en $DOMAIN:$PORT"
echo "Archivo: dynamic/app-$APP_NAME.yml"
```

### Automatización con Scripts

```bash
# scripts/backup-certs.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
tar -czf "backups/traefik-certs-$DATE.tar.gz" certs/
echo "Certificados respaldados en backups/traefik-certs-$DATE.tar.gz"

# scripts/check-health.sh
#!/bin/bash
SERVICES=$(curl -s http://localhost:8080/api/http/services | jq -r '.[] | select(.status != "enabled") | .name')
if [[ -n "$SERVICES" ]]; then
    echo "⚠️  Servicios con problemas: $SERVICES"
    exit 1
else
    echo "✅ Todos los servicios están saludables"
fi
```

## 📈 Optimización de Rendimiento

### Configuración de Performance

```yaml
# traefik.yml - Optimizaciones
entryPoints:
  web:
    address: ":80"
    transport:
      keepAliveMaxRequests: 100
      keepAliveMaxTime: "10s"

  websecure:
    address: ":443"
    transport:
      keepAliveMaxRequests: 100
      keepAliveMaxTime: "10s"
    http:
      tls:
        options: modern@file

# Connection pooling
serversTransport:
  maxIdleConnsPerHost: 50
  dialTimeout: "30s"
  responseHeaderTimeout: "0s"
  idleConnTimeout: "90s"
```

### Caching y Compresión

```yaml
# Middleware de compresión optimizada
http:
  middlewares:
    compression:
      compress:
        excludedContentTypes:
          - "text/event-stream"
          - "application/grpc"
        minResponseBodyBytes: 1024

    # Cache headers
    cache-headers:
      headers:
        customResponseHeaders:
          Cache-Control: "public, max-age=3600"
          Vary: "Accept-Encoding"
```

## 🤝 Contribución

1. Hacer fork del repositorio
2. Crear una rama de feature
3. Añadir configuraciones en `dynamic/` o `templates/`
4. Probar configuraciones localmente
5. Documentar cambios en este README
6. Enviar pull request

### Guías de Configuración

- Usar plantillas para configuraciones repetitivas
- Documentar todos los middlewares personalizados
- Probar certificados SSL antes del despliegue
- Seguir principios de configuración inmutable
- Mantener backups regulares de certificados

## 📝 Notas de Desarrollo

- **Descubrimiento Automático**: Traefik detecta servicios vía labels Docker
- **Recarga en Caliente**: Cambios de configuración sin reinicio
- **Gestión de Certificados**: Renovación automática Let's Encrypt
- **Monitoreo Integrado**: Dashboard web y métricas Prometheus
- **Seguridad por Defecto**: Headers de seguridad y TLS moderno
- **Escalabilidad**: Soporte para múltiples backends y load balancing