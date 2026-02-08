# API - Go Backend Service

The REST API that powers [cubelab.cloud](https://cubelab.cloud). Built with Go, it handles newsletter subscriptions, lead magnets, and other backend services.

 What it does

This API serves as the backend for my personal website. It's pretty straightforward - it handles newsletter subscriptions through Beehiiv, manages lead magnet downloads, and provides health check endpoints for monitoring.

 Tech stack

- Go .+ - Fast, simple, gets the job done
- Gin - Lightweight web framework
- Beehiiv API - Newsletter management
- Zerolog - Structured logging
- Docker - Containerized for easy deployment

 Project structure

```
src/
├── cmd/server/main.go           Application entry point
├── internal/
│   ├── api/                     HTTP endpoints
│   │   ├── healthchecks.go      Health check endpoints
│   │   ├── lead_magnet.go       Lead magnet handling
│   │   ├── middleware.go        CORS and other middleware
│   │   ├── subscribe.go         Newsletter subscriptions
│   │   └── unsubscribe.go       Unsubscription handling
│   ├── models/                  Data structures
│   └── services/                Business logic
│       ├── beehiiv.go           Beehiiv integration
│       ├── email.go             Email services
│       └── subscription.go      Subscription logic
├── pkg/                         Shared packages
│   ├── config/env.go            Environment configuration
│   └── logger/logger.go         Logging setup
└── Dockerfile                   Container definition
```

 Available endpoints

 Health checks
- `GET /health` - Basic health check
- `GET /healthz` - Kubernetes-style health check
- `GET /ready` - Readiness probe

 Newsletter and lead magnets
- `POST /api/subscribe` - Subscribe to newsletter
- `POST /api/unsubscribe` - Unsubscribe from newsletter
- `POST /api/lead-magnet` - Download free resources

 Configuration

 Environment variables

```bash
 Basic configuration
PORT=
LOG_LEVEL=info
GIN_MODE=release

 Beehiiv integration
BEEHIIV_API_KEY=your_api_key_here
BEEHIIV_PUBLICATION_ID=your_publication_id

 CORS configuration
ALLOWED_ORIGINS=https://cubelab.cloud,https://www.cubelab.cloud
```

 Running the API

 Development mode

```bash
 Navigate to the source directory
cd apps/api/src

 Install dependencies
go mod tidy

 Copy environment file and configure it
cp ../.env.example ../.env
 Edit the variables you need

 Run the server
go run cmd/server/main.go
```

 With Docker

```bash
 Development with hot reload
make up-api

 Production mode
docker-compose -f docker-compose.prod.yml up -d
```

 Development commands

```bash
 Format code
go fmt ./...

 Run tests
go test ./...

 Hot reload with air
air
```

 Usage examples

 Subscribe to newsletter

```bash
curl -X POST http://localhost:/api/subscribe \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "tag": "newsletter"}'
```

 Download lead magnet

```bash
curl -X POST http://localhost:/api/lead-magnet \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "resource_id": "devops-checklist",
    "file_id": "checklist-pdf",
    "tags": ["devops", "checklist"],
    "utm_source": "website"
  }'
```

 Monitoring and logging

 Structured logging
Uses Zerolog for JSON structured logging, which helps with:
- Request tracking with unique IDs
- Error tracking with stack traces
- Performance metrics
- Configurable log levels

 Health monitoring
- `/health` - Basic alive check
- `/healthz` - Kubernetes health check
- `/ready` - Readiness for traffic

 Metrics tracked
- Response time per endpoint
- Error rates
- Subscription conversion rates
- External service status

 Security features

- CORS configuration - Only accepts requests from allowed domains
- Input validation - All incoming data is validated
- Rate limiting - Prevents abuse
- Security headers - Standard security headers applied
- Environment separation - Clear dev/staging/production boundaries

 CI/CD integration

This API is part of the automated pipeline:
- Automatic tests on every pull request
- Multi-architecture Docker builds (AMD, ARM)
- Independent versioning using tags like `api-v..`
- Health checks after each deployment

Versioning is automatic based on conventional commits.

 Key dependencies

 Production
- gin-gonic/gin - Web framework
- rs/zerolog - Structured logging
- joho/godotenv - Environment variable loading

 Development
- air - Hot reload for development
- go vet - Code quality checks

 Contributing

. Follow Go conventions - Use `gofmt` and `golint`
. Add tests for any new endpoints
. Update documentation if you change the API
. Use conventional commits for automatic versioning
. Ensure Docker build works before pushing

 Connections

This API works with:
- Web app (`apps/web`) - Astro frontend
- Blog (`apps/blog`) - Jekyll blog
- Wiki (`apps/wiki`) - This documentation
- Beehiiv - Newsletter management service
- Traefik - Reverse proxy for routing

 Development notes

Started simple and grew as needed. When adding features, keep it simple - that's what I like most about Go. The codebase is designed to be easy to understand and modify.

 Local development URLs

When running locally with `make up-api`:
- API: http://api.cubelab.test
- Health: http://api.cubelab.test/health
- Docs: Check the endpoints section above

Add `... api.cubelab.test` to your `/etc/hosts` file.
