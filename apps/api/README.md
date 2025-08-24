# Servicio API Backend

Servicio API REST basado en Go para la plataforma mlorente.dev, gestionando suscripciones, lead magnets y lógica de negocio.

## 🏗️ Arquitectura

- **Framework**: Gin (framework web HTTP de Go)
- **Lenguaje**: Go 1.23+
- **Base de datos**: Integración con API de Beehiiv
- **Logging**: Zerolog (logging estructurado)
- **Contenedor**: Docker con builds multi-etapa

## 📁 Estructura del Proyecto

```
src/
├── cmd/
│   └── server/
│       └── main.go           # Punto de entrada de la aplicación
├── internal/
│   ├── api/
│   │   ├── healthchecks.go   # Endpoints de verificación de salud
│   │   ├── lead_magnet.go    # Gestión de lead magnets
│   │   ├── middleware.go     # CORS y otros middleware
│   │   ├── routes.go         # Definición de rutas
│   │   ├── subscribe.go      # Endpoints de suscripción
│   │   └── unsubscribe.go    # Endpoints de cancelación de suscripción
│   ├── constants/
│   │   ├── messages.go       # Mensajes de la aplicación
│   │   └── pages.go          # Constantes de páginas
│   ├── models/
│   │   ├── resource.go       # Modelos de recursos
│   │   └── subscription.go   # Modelos de suscripción
│   └── services/
│       ├── beehiiv.go        # Integración con API de Beehiiv
│       ├── business.go       # Lógica de negocio
│       ├── email.go          # Servicios de email
│       └── subscription.go   # Servicios de suscripción
├── pkg/
│   ├── config/
│   │   └── env.go            # Configuración de entorno
│   └── logger/
│       └── logger.go         # Configuración de logging estructurado
├── go.mod                    # Módulos de Go
├── go.sum                    # Checksum de dependencias
└── Dockerfile                # Definición de build del contenedor
```

## 🚀 Endpoints de la API

### Verificación de Salud
- `GET /health` - Verificación de salud básica
- `GET /healthz` - Verificación de salud estilo Kubernetes
- `GET /ready` - Sonda de preparación

### Gestión de Suscripciones
- `POST /api/subscribe` - Suscribir usuario al newsletter
- `POST /api/unsubscribe` - Cancelar suscripción del usuario
- `POST /api/lead-magnet` - Gestionar solicitudes de lead magnet

## 🔧 Configuración

### Variables de Entorno

```bash
# Configuración del servidor
PORT=8080
LOG_LEVEL=info
GIN_MODE=release

# Integración con Beehiiv
BEEHIIV_API_KEY=tu_clave_api_aqui
BEEHIIV_PUBLICATION_ID=tu_id_publicacion

# Configuración CORS
ALLOWED_ORIGINS=https://mlorente.dev,https://www.mlorente.dev
```

### Variables de Entorno Docker

Configuradas en el archivo `.env` para el despliegue con Docker:

```bash
# Configuración del contenedor
REGISTRY=docker.io/mlorentedev
IMAGE_NAME=mlorente-api
CONTAINER_NAME=api
TAG=latest
PORT=8080

# Entorno de la aplicación
ENVIRONMENT=production
```

## 🐳 Despliegue con Docker

### Desarrollo
```bash
# Construir y ejecutar localmente
docker-compose -f docker-compose.dev.yml up --build

# Verificar logs
docker-compose -f docker-compose.dev.yml logs -f
```

### Producción
```bash
# Desplegar con configuración de producción
docker-compose -f docker-compose.prod.yml up -d

# Monitorear contenedor
docker logs -f api
```

## 🛠️ Desarrollo Local

### Prerrequisitos
- Go 1.23 o superior
- Docker y Docker Compose (opcional)
- Make (opcional, para comandos de conveniencia)

### Configuración
```bash
# Clonar el repositorio
git clone <url-del-repositorio>
cd apps/api

# Instalar dependencias
cd src && go mod tidy

# Copiar archivo de entorno
cp .env.example .env
# Editar .env con tu configuración

# Ejecutar la aplicación
go run cmd/server/main.go
```

### Comandos de Desarrollo
```bash
# Formatear código
go fmt ./...

# Ejecutar tests
go test ./...

# Construir binario
go build -o api cmd/server/main.go

# Ejecutar con recarga en vivo (con air)
air
```

## 📝 Ejemplos de Uso de la API

### Suscribirse al Newsletter
```bash
curl -X POST http://localhost:8080/api/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "tag": "newsletter"}'
```

### Solicitar Lead Magnet
```bash
curl -X POST http://localhost:8080/api/lead-magnet \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "resource_id": "devops-checklist",
    "file_id": "checklist-pdf",
    "tags": ["devops", "checklist"],
    "utm_source": "website"
  }'
```

### Verificación de Salud
```bash
curl http://localhost:8080/health
```

## 🔍 Monitoreo y Observabilidad

### Logging Estructurado
La API utiliza Zerolog para logging estructurado en JSON:
- Logging de Request/Response con IDs de correlación
- Seguimiento de errores con stack traces
- Logging de métricas de rendimiento
- Niveles de log configurables

### Verificaciones de Salud
- `/health` - Salud básica de la aplicación
- `/healthz` - Sonda de vivacidad de Kubernetes
- `/ready` - Sonda de preparación de Kubernetes

### Métricas
La aplicación expone métricas para:
- Duración de solicitudes HTTP
- Tasas de error por endpoint
- Tasas de conversión de suscripciones
- Salud de integraciones de API

## 🔒 Características de Seguridad

- **Protección CORS**: Orígenes permitidos configurables
- **Validación de Entrada**: Validación del cuerpo de solicitud
- **Limitación de Tasa**: Regulación de solicitudes incorporada
- **Cabeceras de Seguridad**: Cabeceras de seguridad estándar
- **Aislamiento de Entorno**: Configuraciones separadas por entorno

## 🚀 Integración CI/CD

La API es parte del pipeline CI/CD del monorepo:
- **Testing Automático**: Ejecutado en pull requests
- **Construcción Docker**: Builds multi-arquitectura
- **Versionado Independiente**: Versionado semántico específico por app
- **Verificaciones de Salud**: Verificación de despliegue

### Gestión de Versiones
- Utiliza tags específicos por app: `api-v1.2.3`
- Versionado semántico basado en análisis de commits
- Versiones RC para rama develop
- Versiones estables para rama main

## 🤝 Contribuir

1. Seguir las mejores prácticas y convenciones de Go
2. Añadir tests para nuevos endpoints
3. Actualizar documentación para cambios en la API
4. Usar commits convencionales para generación de changelog
5. Asegurar que las construcciones Docker sean exitosas

## 📦 Dependencias

### Core
- **gin-gonic/gin**: Framework web HTTP
- **rs/zerolog**: Logging estructurado
- **joho/godotenv**: Carga de variables de entorno

### Desarrollo
- **air**: Recarga en vivo para desarrollo
- **golangci-lint**: Linting de código

## 🔗 Servicios Relacionados

- **Frontend Web**: `apps/web` - Sitio web basado en Astro
- **Blog**: `apps/blog` - Blog en Jekyll
- **Wiki**: `apps/wiki` - Servicio de documentación
- **Infraestructura**: `infra/` - Configuraciones de despliegue