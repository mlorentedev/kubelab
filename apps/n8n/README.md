# n8n - Automatización de Flujos de Trabajo

Plataforma de automatización de flujos de trabajo auto-alojada para conectar APIs, servicios y bases de datos con diseño visual de flujos de trabajo y potentes capacidades de automatización.

## 🏗️ Arquitectura

- **Plataforma**: n8n.io - Herramienta de automatización de flujos de trabajo visuales
- **Despliegue**: Dockerizado con persistencia de datos
- **Sincronización**: Git-sync para control de versiones de flujos de trabajo
- **Almacenamiento**: Volúmenes persistentes para flujos de trabajo y credenciales
- **Red**: Red proxy externa para acceso de proxy reverso

## 📁 Estructura del Proyecto

```
apps/n8n/
├── README.md              # Esta documentación
├── docker-compose.yml     # Servicios n8n y git-sync
├── flows/                 # Exportaciones y backups de flujos de trabajo
│   └── (archivos de flujos) # Definiciones de flujos de trabajo en JSON
└── .env                   # Variables de entorno (no en repositorio)
```

## 🚀 Características

### Características Principales de n8n

- **Diseñador Visual de Flujos**: Creación de flujos basada en nodos con arrastrar y soltar
- **400+ Integraciones**: Nodos pre-construidos para servicios y APIs populares
- **Ejecución de Código Personalizado**: Nodos de código JavaScript y Python
- **Transformación de Datos**: Manipulación y formato de datos poderoso
- **Lógica Condicional**: Condiciones IF/ELSE y lógica de enrutamiento
- **Manejo de Errores**: Mecanismos completos de captura de errores y reintentos

### Capacidades de Flujos de Trabajo

- **Integración API**: Solicitudes HTTP, webhooks y llamadas a API REST
- **Operaciones de Base de Datos**: Consultas SQL, triggers de base de datos y sincronización de datos
- **Procesamiento de Archivos**: Procesamiento y transformación de CSV, JSON, XML
- **Automatización de Email**: Enviar/recibir emails con plantillas y archivos adjuntos
- **Programación**: Triggers basados en cron y automatización basada en tiempo
- **Monitoreo**: Historial de ejecución de flujos de trabajo y métricas de rendimiento

### Características Empresariales

- **Soporte Multi-usuario**: Colaboración en equipo y compartición de flujos de trabajo
- **Acceso Basado en Roles**: Permisos de usuario y control de acceso a flujos de trabajo
- **Gestión de Credenciales**: Almacenamiento seguro de claves API y contraseñas
- **Plantillas de Flujos**: Patrones de flujos de trabajo reutilizables y ejemplos
- **Control de Versiones**: Integración Git para backup y sincronización de flujos
- **Gestión de Entornos**: Flujos de trabajo de desarrollo, staging y producción

### Sincronización Git

- **Backup Automático**: Backup regular de flujos de trabajo al repositorio Git
- **Historial de Versiones**: Seguimiento completo de cambios de flujos de trabajo
- **Colaboración**: Desarrollo de flujos de trabajo basado en equipos
- **Recuperación ante Desastres**: Restauración de flujos de trabajo desde backup Git
- **Integración CI/CD**: Pipelines de despliegue de flujos de trabajo

## 🔧 Configuración

### Variables de Entorno

Crea un archivo `.env` con la siguiente configuración:

```bash
# Configuración Principal n8n
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=tu-contraseña-segura

# Configuración Avanzada n8n
N8N_HOST=n8n.tudominio.com
N8N_PROTOCOL=https
N8N_PORT=5678
N8N_EDITOR_BASE_URL=https://n8n.tudominio.com/

# Configuración de Base de Datos (opcional)
DB_TYPE=postgresdb
DB_POSTGRESDB_HOST=postgres
DB_POSTGRESDB_PORT=5432
DB_POSTGRESDB_DATABASE=n8n
DB_POSTGRESDB_USER=n8n
DB_POSTGRESDB_PASSWORD=tu-contraseña-bd

# Configuración de Webhook
N8N_WEBHOOK_TUNNEL_URL=https://n8n.tudominio.com/
WEBHOOK_URL=https://n8n.tudominio.com/

# Configuración de Seguridad
N8N_SECURE_COOKIE=true
N8N_JWT_SECRET=tu-clave-secreta-jwt

# Configuración Git Sync
GIT_SYNC_REPO=https://github.com/usuario/n8n-workflows.git
GIT_SYNC_BRANCH=main
GIT_SYNC_USERNAME=tu-usuario
GIT_SYNC_PASSWORD=tu-token-acceso-personal
GIT_SYNC_ROOT=/git
GIT_SYNC_DEST=workflows
GIT_SYNC_PERIOD=300s
GIT_SYNC_ONE_TIME=false

# Opcional: Configuración de Email
N8N_EMAIL_MODE=smtp
N8N_SMTP_HOST=smtp.gmail.com
N8N_SMTP_PORT=587
N8N_SMTP_USER=tu-email@gmail.com
N8N_SMTP_PASS=tu-contraseña-app
N8N_SMTP_SENDER=tu-email@gmail.com
```

### Configuración Avanzada

```bash
# Optimización de Rendimiento
N8N_PAYLOAD_SIZE_MAX=16
N8N_METRICS=true
EXECUTIONS_TIMEOUT=300
EXECUTIONS_TIMEOUT_MAX=3600

# Configuración de Logging
N8N_LOG_LEVEL=info
N8N_LOG_OUTPUT=console,file
N8N_LOG_FILE_LOCATION=/home/node/.n8n/n8n.log

# Nodos Personalizados
N8N_CUSTOM_EXTENSIONS=/home/node/.n8n/custom

# Ejecución de Flujos
EXECUTIONS_PROCESS=main
EXECUTIONS_MODE=regular
EXECUTIONS_DATA_SAVE_ON_ERROR=all
EXECUTIONS_DATA_SAVE_ON_SUCCESS=all
EXECUTIONS_DATA_MAX_AGE=168

# Configuración de Cola (Redis requerido)
QUEUE_BULL_REDIS_HOST=redis
QUEUE_BULL_REDIS_PORT=6379
QUEUE_BULL_REDIS_DB=0
```

## 🐳 Despliegue Docker

### Arquitectura de Servicios

El despliegue de n8n incluye dos servicios principales:

1. **n8n**: Plataforma principal de automatización con motor de ejecución de flujos
2. **git-sync**: Sincronización continua con repositorio Git para flujos de trabajo

### Gestión de Volúmenes

```yaml
volumes:
  n8n_data:           # Datos de usuario, flujos, credenciales y logs
  vault:              # Ubicación de sincronización del repositorio Git
```

### Configuración de Red

Los servicios se conectan a la red externa `proxy` para acceso de proxy reverso.

### Despliegue de Desarrollo

```bash
# Crear red proxy externa (si no existe)
docker network create proxy

# Crear archivo de entorno
cp .env.example .env
vim .env  # Configurar tus ajustes

# Iniciar servicios n8n
docker-compose up -d

# Ver logs
docker-compose logs -f n8n
docker-compose logs -f git_sync

# Acceder a interfaz n8n
open http://localhost:5678
```

### Despliegue de Producción

```bash
# Descargar imágenes más recientes
docker-compose pull

# Iniciar servicios con políticas de reinicio
docker-compose up -d

# Verificar que los servicios estén ejecutándose
docker-compose ps

# Verificar salud de n8n
curl -f http://localhost:5678/healthz

# Monitorear logs
docker-compose logs -f
```

## 🛠️ Desarrollo Local

### Prerrequisitos

- **Docker**: Entorno de ejecución de contenedores
- **Docker Compose**: Orquestación de múltiples contenedores
- **Repositorio Git**: Control de versiones para flujos de trabajo (opcional)
- **Acceso de Red**: Red proxy externa para integración con proxy reverso

### Configuración

```bash
# Navegar al directorio n8n
cd apps/n8n

# Crear configuración de entorno
cat > .env << EOF
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=contraseña-local-segura
N8N_HOST=localhost
N8N_PORT=5678
N8N_PROTOCOL=http
EOF

# Iniciar entorno de desarrollo
docker-compose up -d

# Acceder a n8n en http://localhost:5678
```

### Comandos de Desarrollo

```bash
# Ver logs de n8n
docker-compose logs -f n8n

# Reiniciar servicio n8n
docker-compose restart n8n

# Exportar flujos de trabajo
docker-compose exec n8n n8n export:workflow --all --output=/tmp/workflows.json

# Importar flujos de trabajo
docker-compose exec n8n n8n import:workflow --input=/tmp/workflows.json

# Limpiar datos (destructivo)
docker-compose down -v

# Backup de flujos de trabajo
docker-compose exec n8n cp -r /home/node/.n8n/workflows ./backup/
```

## 📋 Desarrollo de Flujos de Trabajo

### Crear Flujos de Trabajo

1. **Acceder a Interfaz**: Navegar a http://localhost:5678
2. **Autenticación**: Usar credenciales del archivo `.env`
3. **Nuevo Flujo**: Hacer clic en botón "New Workflow"
4. **Añadir Nodos**: Arrastrar y soltar nodos desde la barra lateral
5. **Configurar Nodos**: Establecer parámetros y conexiones de nodos
6. **Probar Ejecución**: Usar botón "Execute Workflow"
7. **Guardar Flujo**: Nombrar y guardar tu flujo de trabajo

### Patrones Comunes de Flujos de Trabajo

#### Procesamiento de Datos API

```
Trigger Webhook → Solicitud HTTP → Nodo Set → Archivo Hoja de Cálculo
```

#### Sincronización de Datos Programada

```
Trigger Cron → Base de Datos → Transformar Datos → Solicitud HTTP → Email
```

#### Procesamiento de Archivos

```
Vigilar Carpeta → Leer Archivo Binario → Parser CSV → Base de Datos → Notificación
```

#### Sistema de Alertas

```
Solicitud HTTP → Nodo IF → Email/Slack → Log → Manejador de Errores
```

### Ejemplos de Configuración de Nodos

#### Trigger Webhook

```json
{
  "httpMethod": "POST",
  "path": "webhook-endpoint",
  "responseMode": "responseNode",
  "authentication": "none"
}
```

#### Nodo Solicitud HTTP

```json
{
  "url": "https://api.ejemplo.com/data",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer {{$credentials.api_token}}",
    "Content-Type": "application/json"
  },
  "timeout": 10000
}
```

#### Nodo Código (JavaScript)

```javascript
// Procesar datos entrantes
const items = $input.all();
const processedItems = [];

for (const item of items) {
  processedItems.push({
    json: {
      id: item.json.id,
      name: item.json.name.toUpperCase(),
      processed_at: new Date().toISOString(),
      status: 'processed'
    }
  });
}

return processedItems;
```

## 🔐 Seguridad y Credenciales

### Gestión de Credenciales

1. **Acceder a Credenciales**: Ir al menú Credentials
2. **Añadir Credencial**: Elegir tipo de credencial
3. **Configurar Autenticación**: Introducir claves API, tokens u OAuth
4. **Probar Conexión**: Verificar funcionalidad de credencial
5. **Usar en Flujos**: Referenciar credenciales en nodos

### Mejores Prácticas de Seguridad

```bash
# Usar variables de entorno para datos sensibles
N8N_BASIC_AUTH_PASSWORD=${CONTRASEÑA_FUERTE}
N8N_JWT_SECRET=${SECRETO_JWT_ALEATORIO}

# Habilitar HTTPS en producción
N8N_PROTOCOL=https
N8N_SECURE_COOKIE=true

# Restringir acceso con autenticación básica
N8N_BASIC_AUTH_ACTIVE=true

# Configurar ajustes CORS apropiados
N8N_CORS_ORIGIN=https://tu-dominio.com
```

### Tipos de Credenciales

- **Clave API**: Autenticación simple con clave API
- **OAuth1/OAuth2**: Autenticación con flujo OAuth
- **Autenticación Básica**: Autenticación con usuario/contraseña
- **Autenticación Header**: Autenticación con header personalizado
- **JWT**: Autenticación con JSON Web Token
- **Base de Datos**: Credenciales de conexión a base de datos

## 🔄 Sincronización de Flujos Git

### Configuración Git-sync

El servicio git-sync sincroniza automáticamente flujos de trabajo con un repositorio Git:

```yaml
git_sync:
  image: registry.k8s.io/git-sync/git-sync:v4.2.3
  environment:
    - GIT_SYNC_REPO=https://github.com/usuario/n8n-workflows.git
    - GIT_SYNC_BRANCH=main
    - GIT_SYNC_PERIOD=300s
    - GIT_SYNC_ROOT=/git
    - GIT_SYNC_DEST=workflows
```

### Estrategia de Backup de Flujos

1. **Exportación Automática**: Flujos de trabajo exportados a archivos JSON
2. **Commit Git**: Cambios confirmados al repositorio
3. **Control de Versiones**: Historial completo de cambios de flujos
4. **Verificación de Backup**: Verificaciones regulares de integridad de backup
5. **Proceso de Restauración**: Procedimientos de recuperación ante desastres

### Operaciones Manuales de Flujos

```bash
# Exportar todos los flujos de trabajo
docker-compose exec n8n n8n export:workflow --all --output=/home/node/.n8n/backup/

# Importar flujos de trabajo desde backup
docker-compose exec n8n n8n import:workflow --input=/home/node/.n8n/backup/workflows.json

# Exportar flujo específico
docker-compose exec n8n n8n export:workflow --id=5 --output=/tmp/workflow.json

# Listar todos los flujos de trabajo
docker-compose exec n8n n8n list:workflow
```

## 📊 Monitoreo y Logging

### Monitoreo de Ejecución

```bash
# Ver logs de ejecución de flujos de trabajo
docker-compose logs -f n8n | grep "Workflow execution"

# Monitorear llamadas webhook
docker-compose logs -f n8n | grep "webhook"

# Verificar logs de error
docker-compose logs -f n8n | grep "ERROR"
```

### Métricas de Rendimiento

- **Tiempo de Ejecución**: Duración de ejecución de flujos de trabajo
- **Tasa de Éxito**: Porcentaje de ejecuciones exitosas
- **Tasa de Error**: Frecuencia de ejecuciones fallidas
- **Uso de Recursos**: Consumo de CPU y memoria
- **Longitud de Cola**: Ejecuciones de flujos de trabajo pendientes

### Verificaciones de Salud

```bash
# Endpoint de salud n8n
curl -f http://localhost:5678/healthz

# Verificar estado de flujo de trabajo
curl -X GET http://localhost:5678/rest/executions \
  -H "Authorization: Basic $(echo -n admin:contraseña | base64)"

# Monitorear estado git-sync
docker-compose logs -f git_sync | tail -20
```

## 🔗 Ejemplos de Integración

### Integraciones Comunes

#### Automatización de Suscripción Newsletter

```
Webhook → Validar Email → Añadir a Lista de Correo → Enviar Email Bienvenida
```

#### Monitoreo de Redes Sociales

```
API Twitter → Filtrar Palabras Clave → Análisis de Sentimientos → Notificación Slack
```

#### Sincronización de Base de Datos

```
Trigger Base de Datos → Transformar Datos → Solicitud HTTP → Actualizar Registro
```

#### Pipeline de Procesamiento de Archivos

```
Trigger Google Drive → Descargar Archivo → Procesar CSV → Subir a S3
```

### Conexiones a Servicios Externos

```bash
# Integración Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_BOT_TOKEN=xoxb-...

# Servicios Email
SMTP_HOST=smtp.gmail.com
SMTP_USER=tu-email@gmail.com
SMTP_PASS=contraseña-específica-app

# Conexiones Base de Datos
DATABASE_URL=postgres://user:pass@host:port/db
REDIS_URL=redis://localhost:6379
```

## 🚀 Optimización de Rendimiento

### Configuración de Ejecución

```bash
# Aumentar timeout para flujos de larga duración
EXECUTIONS_TIMEOUT=3600
EXECUTIONS_TIMEOUT_MAX=7200

# Optimizar uso de memoria
N8N_PAYLOAD_SIZE_MAX=32
NODE_OPTIONS="--max-old-space-size=4096"

# Configurar ajustes de cola
EXECUTIONS_PROCESS=own
QUEUE_BULL_REDIS_HOST=redis
```

### Mejores Prácticas de Flujos

1. **Minimizar Recuento de Nodos**: Combinar operaciones donde sea posible
2. **Usar Nodos Set**: Optimizar transformación de datos
3. **Manejo de Errores**: Añadir captura apropiada de errores
4. **Gestión de Recursos**: Limitar ejecuciones concurrentes
5. **Validación de Datos**: Validar entradas y salidas
6. **Monitoreo**: Añadir logging y notificaciones

### Gestión de Recursos

```bash
# Límites de memoria en docker-compose
n8n:
  deploy:
    resources:
      limits:
        memory: 2G
      reservations:
        memory: 512M
```

## 🔧 Personalización

### Nodos Personalizados

```bash
# Crear directorio de nodos personalizados
mkdir -p custom-nodes/n8n-nodes-custom

# Instalar nodos personalizados
docker-compose exec n8n npm install n8n-nodes-custom

# Reiniciar n8n para cargar nuevos nodos
docker-compose restart n8n
```

### Configuración Específica por Entorno

```bash
# Entorno desarrollo
N8N_WEBHOOK_TUNNEL_URL=http://localhost:5678/
N8N_LOG_LEVEL=debug

# Entorno staging
N8N_WEBHOOK_TUNNEL_URL=https://n8n-staging.tudominio.com/
N8N_LOG_LEVEL=info

# Entorno producción
N8N_WEBHOOK_TUNNEL_URL=https://n8n.tudominio.com/
N8N_LOG_LEVEL=warn
EXECUTIONS_DATA_SAVE_ON_SUCCESS=none
```

### Configuración Proxy Reverso

```yaml
# Etiquetas Traefik para n8n
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.n8n.rule=Host(`n8n.tudominio.com`)"
  - "traefik.http.services.n8n.loadbalancer.server.port=5678"
  - "traefik.http.routers.n8n.tls=true"
  - "traefik.http.routers.n8n.tls.certresolver=letsencrypt"
```

## 📈 Casos de Uso

### Automatización de Negocios

- **Procesamiento de Leads**: Integración CRM y puntuación de leads
- **Gestión de Facturas**: Facturación automatizada y procesamiento de pagos
- **Soporte al Cliente**: Enrutamiento de tickets y automatización de respuestas
- **Gestión de Inventario**: Monitoreo de niveles de stock y reordenación
- **Generación de Reportes**: Recolección automatizada de datos y reportes

### Automatización DevOps

- **Pipelines de Despliegue**: Orquestación de flujos CI/CD
- **Alertas de Monitoreo**: Monitoreo de sistemas y respuesta ante incidentes
- **Gestión de Backups**: Programación automatizada de backups y verificación
- **Escaneo de Seguridad**: Evaluación de vulnerabilidades y reportes
- **Aprovisionamiento de Infraestructura**: Gestión automatizada de recursos

### Gestión de Contenido

- **Redes Sociales**: Publicación automatizada y engagement
- **Publicación de Blog**: Creación y distribución de contenido
- **Optimización SEO**: Seguimiento de palabras clave y análisis de contenido
- **Gestión de Assets**: Organización y distribución de archivos
- **Reportes de Analytics**: Análisis de tráfico y rendimiento

## 🤝 Contribución

1. Hacer fork del repositorio
2. Crear una rama de feature para adiciones de flujos
3. Añadir documentación de flujos en directorio `flows/`
4. Probar flujos en entorno de desarrollo
5. Exportar flujos como archivos JSON
6. Enviar pull request con descripciones de flujos

### Documentación de Flujos

```markdown
# Flujo: Pipeline de Procesamiento de Datos

## Propósito
Procesar datos CSV entrantes y sincronizar con base de datos

## Trigger
Webhook HTTP en /webhook/data-import

## Pasos
1. Validar formato CSV
2. Transformar estructura de datos
3. Actualizar registros de base de datos
4. Enviar email de confirmación

## Configuración
- Base de Datos: Conexión PostgreSQL requerida
- Email: Configuración SMTP en credenciales
- Webhook: Solicitudes POST con datos CSV
```

## 📝 Notas de Desarrollo

- **Persistencia de Datos**: Todos los flujos y configuraciones almacenados en volúmenes Docker
- **Seguridad de Red**: Los servicios se comunican vía red interna Docker
- **Seguridad de Credenciales**: Almacenamiento encriptado de credenciales en base de datos n8n
- **Estrategia de Backup**: Git-sync proporciona backup automatizado de flujos
- **Monitoreo**: Habilitar métricas y logging para entornos de producción
- **Rendimiento**: Monitorear regularmente tiempos de ejecución y uso de recursos