# Mi API Backend en Go

<div align="center">

![Go](https://img.shields.io/badge/Go-1.23+-00ADD8?style=flat&logo=go&logoColor=white)
![Gin](https://img.shields.io/badge/Gin-008000?style=flat&logo=gin&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-008099?style=flat)

</div>

Esta es mi API REST en Go que maneja toda la lógica de negocio de [mlorente.dev](https://mlorente.dev). Se encarga de las suscripciones al newsletter, los lead magnets y otras cositas que necesita el frontend.

## ⚙️ Qué tecnologías uso

- **Go 1.23+** - Porque es rápido y me gusta su simplicidad
- **Gin** - Framework web que va como un tiro
- **Beehiiv API** - Para gestionar las suscripciones del newsletter
- **Zerolog** - Logging estructurado que me facilita el debug
- **Docker** - Todo containerizado para desplegar fácil

## 📁 Cómo está organizado

```
src/
├── cmd/server/main.go          # Punto de entrada - aquí arranca todo
├── internal/
│   ├── api/                    # Todos los endpoints
│   │   ├── healthchecks.go     # Para saber si está vivo
│   │   ├── lead_magnet.go      # Lead magnets del blog
│   │   ├── middleware.go       # CORS y otras cosas
│   │   ├── subscribe.go        # Suscripciones al newsletter
│   │   └── unsubscribe.go      # Por si alguien se quiere ir
│   ├── models/                 # Estructuras de datos
│   └── services/               # La lógica de negocio
│       ├── beehiiv.go          # Integración con Beehiiv
│       ├── email.go            # Todo lo de emails
│       └── subscription.go     # Gestión de suscripciones
├── pkg/                        # Código reutilizable
│   ├── config/env.go           # Variables de entorno
│   └── logger/logger.go        # Configuración del logging
├── go.mod & go.sum             # Dependencias
└── Dockerfile                  # Para containerizar
```

## 🎯 Endpoints disponibles

### ¿Está viva la API?
- `GET /health` - Check básico
- `GET /healthz` - Para Kubernetes
- `GET /ready` - Para saber si está lista

### Newsletter y lead magnets
- `POST /api/subscribe` - Suscribirse al newsletter
- `POST /api/unsubscribe` - Cancelar suscripción
- `POST /api/lead-magnet` - Descargar recursos gratuitos

## 🔧 Configuración

### Variables que necesitas

```bash
# Configuración básica
PORT=8080
LOG_LEVEL=info
GIN_MODE=release

# Para conectar con Beehiiv
BEEHIIV_API_KEY=tu_clave_aqui
BEEHIIV_PUBLICATION_ID=tu_id_aqui

# CORS (importante para el frontend)
ALLOWED_ORIGINS=https://mlorente.dev,https://www.mlorente.dev
```

### Para Docker

```bash
# Configuración del contenedor
REGISTRY=docker.io/mlorentedev
IMAGE_NAME=mlorente-api
CONTAINER_NAME=api
TAG=latest
PORT=8080
ENVIRONMENT=production
```

## 🚀 Cómo ejecutar esto

### En desarrollo (rápido y sucio)

```bash
# Clona el repo y ve a la carpeta
cd apps/api/src

# Instala las dependencias
go mod tidy

# Copia el archivo de ejemplo y configúralo
cp ../.env.example ../.env
# Edita las variables que necesites

# ¡A funcionar!
go run cmd/server/main.go
```

### Con Docker (como en producción)

```bash
# Para desarrollo con hot reload
docker-compose -f docker-compose.dev.yml up --build

# Para producción
docker-compose -f docker-compose.prod.yml up -d
```

### Comandos útiles para desarrollar

```bash
# Formatear el código (Go es muy quisquilloso)
go fmt ./...

# Ejecutar tests
go test ./...

# Con air para hot reload (súper cómodo)
air
```

## 💡 Ejemplos de uso

### Suscribirse al newsletter

```bash
curl -X POST http://localhost:8080/api/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "tag": "newsletter"}'
```

### Descargar un lead magnet

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

## 📊 Monitoreo y logs

### Logging inteligente
Uso Zerolog para logs estructurados en JSON. Esto me ayuda mucho para:

- Tracking de cada request con IDs únicos
- Seguimiento de errores con stack traces
- Métricas de rendimiento
- Logs configurables por nivel

### Health checks
- `/health` - "¿Estás vivo?"
- `/healthz` - Para que Kubernetes sepa si funciona
- `/ready` - Para saber si está listo para recibir tráfico

### Métricas que rastrea
- Tiempo de respuesta por endpoint
- Tasas de error
- Conversiones de suscripciones
- Estado de las integraciones externas

## 🔒 Seguridad

No soy paranoico, pero me gusta que las cosas estén seguras:

- **CORS configurado** - Solo acepta requests de mis dominios
- **Validación de entrada** - Todo lo que llega se valida
- **Rate limiting** - Para evitar abusos
- **Headers de seguridad** - Los estándar de la industria
- **Entornos separados** - Dev, staging y prod bien diferenciados

## 🔄 CI/CD

Esta API forma parte del pipeline automático:

- **Tests automáticos** en cada pull request
- **Builds multi-arquitectura** con Docker
- **Versionado independiente** - usa tags como `api-v1.2.3`
- **Health checks** tras cada despliegue

El versionado es automático basándose en los commits convencionales. Muy cómodo.

## 🛠️ Dependencias principales

### Las que uso siempre
- **gin-gonic/gin** - El framework web
- **rs/zerolog** - Para logs bonitos
- **joho/godotenv** - Para cargar variables de entorno

### Para desarrollo
- **air** - Hot reload que me ahorra tiempo
- **golangci-lint** - Para que el código esté limpio

## 💡 Tips para contribuir

1. **Sigue las convenciones de Go** - Usa `gofmt` y `golint`
2. **Añade tests** para cualquier endpoint nuevo
3. **Actualiza la documentación** si cambias algo de la API
4. **Commits convencionales** - para que el versionado automático funcione
5. **Asegúrate de que el Docker build funciona** antes de hacer push

## 🔗 Con qué otros servicios se conecta

- **Frontend** (`apps/web`) - Mi sitio web en Astro
- **Blog** (`apps/blog`) - El blog en Jekyll
- **Wiki** (`apps/wiki`) - Esta documentación
- **Beehiiv** - Para gestionar el newsletter
- **Traefik** - Proxy reverso que dirige el tráfico

---

> **Nota personal:** Esta API la empecé simple y ha ido creciendo con las necesidades. Si vas a añadir algo, mantenla simple - que es lo que más me gusta de Go.