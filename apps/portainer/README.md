# Portainer - Gestión Docker

<div align="center">

![Portainer](https://img.shields.io/badge/Portainer-13BEF9?style=for-the-badge&logo=portainer&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Web UI](https://img.shields.io/badge/Web_UI-008099?style=for-the-badge&logo=web&logoColor=white)
![Management](https://img.shields.io/badge/Management-Container-008099?style=for-the-badge)

![Status](https://img.shields.io/badge/Status-Active-008099?style=flat-square)
![Port](https://img.shields.io/badge/Port-9000-blue?style=flat-square)
![Access](https://img.shields.io/badge/Access-Docker_Socket-green?style=flat-square)

</div>

Interfaz web para gestión de Docker que proporciona administración completa de contenedores, imágenes, redes y volúmenes con una GUI intuitiva para entornos Docker.

## 🏗️ Arquitectura

- **Plataforma**: Portainer Community Edition (CE)
- **Interfaz**: Panel de administración web
- **Acceso**: Integración con socket Docker para acceso completo a la API
- **Almacenamiento**: Volumen de datos persistente para configuración y ajustes
- **Red**: Red proxy externa para integración con proxy reverso

## 📁 Estructura del Proyecto

```
apps/portainer/
├── README.md              # Esta documentación
├── docker-compose.yml     # Configuración del servicio Portainer
└── .env                   # Variables de entorno (no en repositorio)
```

## 🚀 Características

### Gestión de Contenedores

- **Ciclo de Vida**: Iniciar, parar, reiniciar y eliminar contenedores
- **Monitoreo en Tiempo Real**: Estadísticas de CPU, memoria y uso de red
- **Visualización de Logs**: Logs de contenedores en vivo con búsqueda y filtrado
- **Acceso a Consola**: Acceso a terminal interactivo de contenedores en ejecución
- **Inspección de Contenedores**: Configuración detallada y metadatos de contenedores
- **Monitoreo de Salud**: Estado de salud y políticas de reinicio de contenedores

### Gestión de Imágenes

- **Registro de Imágenes**: Descargar imágenes de Docker Hub y registros privados
- **Imágenes Locales**: Ver, inspeccionar y gestionar imágenes Docker locales
- **Construcción de Imágenes**: Construir imágenes desde Dockerfiles vía interfaz web
- **Integración de Registros**: Conectar con múltiples registros Docker
- **Historial de Imágenes**: Ver capas de imágenes e historial de construcción
- **Escaneo de Vulnerabilidades**: Análisis de seguridad para vulnerabilidades conocidas

### Gestión de Redes

- **Creación de Redes**: Crear redes Docker con configuraciones personalizadas
- **Inspección de Redes**: Ver topología de red y contenedores conectados
- **Redes Bridge**: Gestionar redes bridge por defecto y personalizadas
- **Redes Overlay**: Gestión de redes overlay de Docker Swarm
- **Drivers de Red**: Soporte para drivers bridge, overlay y personalizados
- **Mapeo de Puertos**: Configurar exposición de puertos de contenedores

### Gestión de Volúmenes

- **Creación de Volúmenes**: Crear y gestionar volúmenes Docker
- **Inspección de Volúmenes**: Ver detalles y estadísticas de uso de volúmenes
- **Bind Mounts**: Configurar montajes de directorios del host
- **Drivers de Volumen**: Soporte para drivers de volumen locales y remotos
- **Backup de Datos**: Funcionalidad de backup y restauración de volúmenes
- **Análisis de Almacenamiento**: Análisis de tamaño y uso de volúmenes

### Características Docker Swarm

- **Gestión Swarm**: Inicializar y gestionar clusters Docker Swarm
- **Despliegue de Servicios**: Desplegar y escalar servicios Docker Swarm
- **Gestión de Stacks**: Desplegar aplicaciones multi-servicio con archivos compose
- **Gestión de Nodos**: Añadir, eliminar y gestionar nodos swarm
- **Gestión de Secretos**: Manejo seguro de datos sensibles
- **Gestión de Configuración**: Gestión de configuración de aplicaciones

### Gestión de Usuarios

- **Soporte Multi-usuario**: Control de acceso basado en roles
- **Autenticación**: Opciones de autenticación local y LDAP
- **Gestión de Equipos**: Organizar usuarios en equipos con permisos
- **Control de Acceso a Recursos**: Controles de acceso granulares a recursos
- **Logging de Auditoría**: Seguimiento de actividad de usuarios y cambios
- **Tokens API**: Acceso programático con autenticación por tokens

## 🔧 Configuración

### Variables de Entorno

Crea un archivo `.env` con la siguiente configuración:

```bash
# Configuración Portainer
PORTAINER_ADMIN_PASSWORD=tu-contraseña-segura
PORTAINER_HOST=portainer.tudominio.com

# Opcional: Configuraciones Avanzadas
PORTAINER_FLAGS=--no-analytics
PORTAINER_TEMPLATES=https://raw.githubusercontent.com/portainer/templates/master/templates.json

# Configuraciones de Seguridad
PORTAINER_LOGO=https://tudominio.com/logo.png
PORTAINER_DISABLE_FEATURE_TOUR=true

# Configuración SSL (si usas certificados personalizados)
PORTAINER_SSL_CERT=/certs/portainer.crt
PORTAINER_SSL_KEY=/certs/portainer.key

# Configuraciones de Base de Datos (para base de datos externa)
PORTAINER_DATABASE=bolt
PORTAINER_DATA_PATH=/data

# Configuraciones de Registro
DOCKER_REGISTRY_URL=registry.tudominio.com
DOCKER_REGISTRY_USERNAME=usuario-registro
DOCKER_REGISTRY_PASSWORD=contraseña-registro
```

### Configuración Avanzada

```bash
# Optimización de Rendimiento
PORTAINER_SNAPSHOT_INTERVAL=5m
PORTAINER_CLEANUP_INTERVAL=24h
PORTAINER_MAX_CONCURRENT_OPERATIONS=10

# Banderas de Características
PORTAINER_HIDE_INTERNAL_AUTH=false
PORTAINER_ENABLE_HOST_MANAGEMENT_FEATURES=true
PORTAINER_ENABLE_EDGE_COMPUTE_FEATURES=false

# Configuración de Logging
PORTAINER_LOG_LEVEL=INFO
PORTAINER_LOG_FORMAT=json

# Configuración de Templates
PORTAINER_TEMPLATE_FILE=/data/templates.json
PORTAINER_APP_TEMPLATES=true
```

## 🐳 Despliegue Docker

### Configuración del Servicio

```yaml
services:
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    ports:
      - "8000:8000"      # Puerto del agente Edge
      - "9443:9443"      # UI HTTPS (opcional)
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # Acceso API Docker
      - portainer_data:/data                        # Almacenamiento persistente
    networks:
      - proxy                                      # Red externa
```

### Consideraciones de Seguridad

```yaml
# Mejoras de seguridad para producción
portainer:
  security_opt:
    - no-new-privileges:true
  read_only: true
  tmpfs:
    - /tmp
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro  # Socket de solo lectura
```

### Despliegue de Desarrollo

```bash
# Crear red proxy externa (si no existe)
docker network create proxy

# Crear archivo de entorno
cat > .env << EOF
PORTAINER_ADMIN_PASSWORD=contraseña-local-segura
PORTAINER_FLAGS=--no-analytics
EOF

# Iniciar Portainer
docker-compose up -d

# Ver logs
docker-compose logs -f portainer

# Acceder a Portainer en http://localhost:9000
```

### Despliegue de Producción

```bash
# Descargar imagen más reciente
docker-compose pull

# Iniciar con política de reinicio
docker-compose up -d

# Verificar estado del servicio
docker-compose ps

# Verificar salud de Portainer
curl -f http://localhost:9000/api/status

# Monitorear inicio
docker-compose logs -f portainer
```

## 🛠️ Desarrollo Local

### Prerrequisitos

- **Docker**: Entorno de ejecución de contenedores
- **Docker Compose**: Orquestación de múltiples contenedores
- **Acceso de Red**: Acceso a socket Docker para gestión
- **Almacenamiento**: Espacio en disco suficiente para datos de contenedores

### Configuración

```bash
# Navegar al directorio Portainer
cd apps/portainer

# Crear configuración de entorno
cat > .env << EOF
PORTAINER_ADMIN_PASSWORD=admin123
PORTAINER_FLAGS=--no-analytics --no-auth
EOF

# Iniciar entorno de desarrollo
docker-compose up -d

# Acceder a interfaz Portainer
open http://localhost:9000
```

### Comandos de Desarrollo

```bash
# Ver logs de Portainer
docker-compose logs -f portainer

# Reiniciar servicio Portainer
docker-compose restart portainer

# Acceder a contenedor Portainer
docker-compose exec portainer sh

# Backup de datos Portainer
docker run --rm -v portainer_portainer_data:/data -v $(pwd)/backup:/backup alpine tar czf /backup/portainer-backup.tar.gz /data

# Restaurar datos Portainer
docker run --rm -v portainer_portainer_data:/data -v $(pwd)/backup:/backup alpine tar xzf /backup/portainer-backup.tar.gz -C /

# Limpiar datos (destructivo)
docker-compose down -v
```

## 🖥️ Uso de la Interfaz Web

### Configuración Inicial

1. **Acceder a Interfaz**: Navegar a http://localhost:9000
2. **Cuenta de Administrador**: Crear cuenta de administrador inicial
3. **Configuración de Entorno**: Elegir entorno Docker local
4. **Panel de Control**: Revisar visión general del entorno Docker
5. **Configuraciones**: Configurar preferencias y ajustes de seguridad

### Visión General del Dashboard

- **Información del Sistema**: Versión Docker, recursos del sistema
- **Resumen de Recursos**: Recuento de contenedores, imágenes, volúmenes, redes
- **Acciones Rápidas**: Tareas de gestión comunes
- **Feed de Actividad**: Eventos recientes de contenedores y sistema
- **Uso de Recursos**: Métricas de CPU, memoria y almacenamiento

### Gestión de Contenedores

```bash
# Operaciones comunes de contenedores vía UI:
1. Iniciar/Parar/Reiniciar contenedores
2. Ver logs de contenedores con actualizaciones en tiempo real
3. Acceder a shell de contenedor (consola)
4. Inspeccionar configuración de contenedor
5. Actualizar configuraciones de contenedor
6. Crear contenedor desde imagen
7. Duplicar contenedor existente
```

### Operaciones de Imágenes

```bash
# Tareas de gestión de imágenes:
1. Descargar imágenes de registros
2. Construir imágenes desde Dockerfile
3. Etiquetar y subir imágenes
4. Eliminar imágenes sin usar
5. Inspeccionar capas de imagen
6. Exportar/Importar imágenes
```

## 📊 Monitoreo y Analytics

### Monitoreo de Recursos

- **Estadísticas de Contenedores**: CPU, memoria, red y E/S de disco en tiempo real
- **Visión General del Sistema**: Utilización de recursos del sistema host
- **Analytics de Almacenamiento**: Uso de almacenamiento de volúmenes e imágenes
- **Tráfico de Red**: Estadísticas de red de contenedores
- **Métricas de Rendimiento**: Datos históricos de rendimiento

### Logging de Actividad

```bash
# Seguimiento de actividad Portainer:
- Eventos de login/logout de usuarios
- Cambios en ciclo de vida de contenedores
- Operaciones de descarga/construcción de imágenes
- Modificaciones de volúmenes y redes
- Cambios de configuración
- Eventos de seguridad
```

### Monitoreo de Salud

```bash
# Endpoints de verificación de salud
curl http://localhost:9000/api/status
curl http://localhost:9000/api/version
curl http://localhost:9000/api/system/info
```

## 🔐 Seguridad y Control de Acceso

### Métodos de Autenticación

```bash
# Autenticación Local (por defecto)
PORTAINER_AUTH_METHOD=internal

# Autenticación LDAP
PORTAINER_AUTH_METHOD=ldap
LDAP_URL=ldap://ldap.empresa.com:389
LDAP_BIND_DN=cn=admin,dc=empresa,dc=com
LDAP_BIND_PASSWORD=contraseña
LDAP_BASE_DN=ou=users,dc=empresa,dc=com

# Autenticación OAuth
PORTAINER_OAUTH_ENABLED=true
OAUTH_PROVIDER=google
OAUTH_CLIENT_ID=tu-client-id
OAUTH_CLIENT_SECRET=tu-client-secret
```

### Control de Acceso Basado en Roles

- **Administrador**: Acceso completo a todos los recursos y configuraciones
- **Usuario Estándar**: Acceso limitado a recursos asignados
- **Usuario Solo Lectura**: Acceso de solo visualización a recursos
- **Roles Personalizados**: Permisos granulares para operaciones específicas

### Mejores Prácticas de Seguridad

```yaml
# Endurecimiento de seguridad
portainer:
  environment:
    - PORTAINER_FLAGS=--no-analytics --ssl-cert=/certs/cert.pem --ssl-key=/certs/key.pem
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro  # Socket de solo lectura
    - ./certs:/certs:ro                             # Certificados SSL
  user: "1000:1000"                                 # Usuario no root
```

### Auditoría y Cumplimiento

- **Logs de Actividad**: Rastro de auditoría completo de acciones de usuarios
- **Seguimiento de Cambios**: Modificaciones de configuración y recursos
- **Logs de Acceso**: Eventos de autenticación y autorización
- **Escaneo de Seguridad**: Evaluaciones de vulnerabilidades de contenedores
- **Reportes de Cumplimiento**: Reportes automatizados de cumplimiento

## 🔗 Puntos de Integración

### Integración CI/CD

```bash
# Ejemplo de Pipeline Jenkins
pipeline {
    agent any
    stages {
        stage('Deploy') {
            steps {
                script {
                    // Desplegar vía API Portainer
                    sh '''
                    curl -X POST "http://portainer:9000/api/stacks" \
                      -H "X-API-Key: ${PORTAINER_API_KEY}" \
                      -F "name=myapp" \
                      -F "stackFileContent=@docker-compose.yml"
                    '''
                }
            }
        }
    }
}
```

### Integración API

```bash
# Autenticar y obtener token JWT
curl -X POST http://localhost:9000/api/auth \
  -H "Content-Type: application/json" \
  -d '{"Username": "admin", "Password": "contraseña"}'

# Usar API con token
curl -X GET http://localhost:9000/api/containers/json \
  -H "Authorization: Bearer TU_JWT_TOKEN"

# Desplegar stack vía API
curl -X POST http://localhost:9000/api/stacks \
  -H "Authorization: Bearer TU_JWT_TOKEN" \
  -F "name=mistack" \
  -F "stackFileContent=@stack.yml"
```

### Integración de Monitoreo

```bash
# Endpoint de métricas Prometheus
curl http://localhost:9000/metrics

# Integración dashboard Grafana
# Usar API Portainer como fuente de datos
# Crear dashboards para métricas de contenedores
```

### Integración de Registros

```bash
# Configurar registros privados
1. Ir a sección Registries
2. Añadir configuración de registro
3. Introducir URL y credenciales de registro
4. Probar conexión
5. Usar registro en despliegues
```

## 🚀 Características Avanzadas

### Gestión Docker Swarm

```bash
# Inicializar Swarm vía UI Portainer:
1. Ir a sección Swarm
2. Hacer clic en "Initialize Swarm"
3. Configurar ajustes Swarm
4. Añadir nodos worker
5. Desplegar servicios y stacks
```

### Despliegue de Stacks

```yaml
# Desplegar aplicaciones multi-servicio
version: '3.8'
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    deploy:
      replicas: 3
      restart_policy:
        condition: on-failure
  
  db:
    image: postgres:13
    environment:
      POSTGRES_DB: miapp
      POSTGRES_USER: usuario
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

secrets:
  db_password:
    external: true
```

### Gestión de Templates

```json
{
  "version": "2",
  "templates": [
    {
      "type": 1,
      "title": "WordPress",
      "description": "WordPress con MySQL",
      "image": "wordpress:latest",
      "env": [
        {
          "name": "WORDPRESS_DB_HOST",
          "label": "Host de base de datos"
        }
      ],
      "ports": ["80/tcp"],
      "volumes": ["/var/www/html"]
    }
  ]
}
```

## 🔧 Personalización

### Templates Personalizados

```bash
# Crear templates de aplicaciones personalizadas
1. Crear archivo JSON de template
2. Subir a templates Portainer
3. Configurar parámetros de template
4. Probar despliegue de template
5. Compartir con miembros del equipo
```

### Branding y Tema

```bash
# Opciones de branding personalizado
PORTAINER_LOGO=https://tudominio.com/logo.png
PORTAINER_TITLE="Gestión Docker Tu Empresa"
PORTAINER_CUSTOM_CSS=https://tudominio.com/custom.css
```

### Configuración Proxy Reverso

```yaml
# Configuración Traefik
portainer:
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.portainer.rule=Host(`portainer.tudominio.com`)"
    - "traefik.http.services.portainer.loadbalancer.server.port=9000"
    - "traefik.http.routers.portainer.tls=true"
    - "traefik.http.routers.portainer.tls.certresolver=letsencrypt"
    - "traefik.http.routers.portainer.middlewares=auth@file"
```

### Configuración Específica por Entorno

```bash
# Entorno de desarrollo
PORTAINER_FLAGS=--no-analytics --no-auth
PORTAINER_TEMPLATE_FILE=/data/dev-templates.json

# Entorno de staging
PORTAINER_FLAGS=--no-analytics
PORTAINER_SNAPSHOT_INTERVAL=1m

# Entorno de producción
PORTAINER_FLAGS=--no-analytics --ssl --ssl-cert=/certs/cert.pem --ssl-key=/certs/key.pem
PORTAINER_SNAPSHOT_INTERVAL=5m
```

## 📈 Mejores Prácticas

### Gestión de Contenedores

1. **Límites de Recursos**: Siempre establecer límites de memoria y CPU
2. **Health Checks**: Configurar verificaciones de salud de contenedores
3. **Políticas de Reinicio**: Usar políticas de reinicio apropiadas
4. **Gestión de Logs**: Configurar rotación y retención de logs
5. **Seguridad**: Ejecutar contenedores con usuarios no root
6. **Segmentación de Red**: Usar redes personalizadas para aislamiento

### Gestión de Imágenes

1. **Versionado**: Usar tags específicas en lugar de 'latest'
2. **Escaneo de Seguridad**: Escanear regularmente imágenes por vulnerabilidades
3. **Optimización de Tamaño**: Usar imágenes base mínimas
4. **Cache de Build**: Optimizar Dockerfile para cache de construcción
5. **Gestión de Registro**: Organizar imágenes con etiquetado apropiado
6. **Limpieza**: Limpieza regular de imágenes sin usar

### Monitoreo y Mantenimiento

1. **Backups Regulares**: Backup automatizado de datos Portainer
2. **Gestión de Actualizaciones**: Mantener Portainer y contenedores actualizados
3. **Monitoreo de Rendimiento**: Monitorear tendencias de uso de recursos
4. **Análisis de Logs**: Revisión regular de logs de contenedores
5. **Planificación de Capacidad**: Monitorear crecimiento de almacenamiento y recursos
6. **Auditorías de Seguridad**: Evaluaciones regulares de seguridad

## 🤝 Contribución

1. Hacer fork del repositorio
2. Crear una rama de feature
3. Añadir o modificar configuraciones Portainer
4. Probar cambios en entorno local
5. Documentar cambios de configuración
6. Enviar pull request

### Guías de Configuración

- Usar variables de entorno para toda configuración sensible
- Documentar todos los templates y configuraciones personalizadas
- Probar configuraciones en desarrollo antes de producción
- Seguir mejores prácticas de seguridad para gestión Docker
- Mantener procedimientos de backup y recuperación

## 📝 Notas de Desarrollo

- **Socket Docker**: Requiere acceso al socket Docker para gestión
- **Persistencia de Datos**: Toda configuración almacenada en volúmenes Docker
- **Seguridad de Red**: Servicios se comunican vía red interna Docker
- **Requerimientos de Recursos**: Requerimientos mínimos de recursos para gestión
- **Estrategia de Backup**: Backup regular de datos y configuraciones Portainer
- **Proceso de Actualización**: Reemplazo simple de contenedor para actualizaciones