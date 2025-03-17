# mlorente.dev

This is my minimal website [mlorente.dev](https://mlorente.dev) with modern architecture based in containers.

This project demonstrates a production-ready microservices approach using containers, seamlessly integrating a static frontend with a dynamic backend. It showcases best practices for development, deployment, and maintenance of a modern web application with minimal JavaScript.

## Technology Stack

- **Frontend**:

  - [Astro](https://astro.build) for static site generation and server-side rendering
  - [HTMX](https://htmx.org) for dynamic content without complex JavaScript
  - [TailwindCSS](https://tailwindcss.com) for utility-first styling
  - Minimal client-side JavaScript for enhanced performance

- **Backend**:
  - [Go](https://golang.org) for high-performance API services
  - Clean architecture with clear separation of concerns
  - RESTful API design principles
  - Structured logging and error handling

- **Infrastructure**:
  - [Docker](https://www.docker.com) for containerization and consistent environments
  - [Docker Compose](https://docs.docker.com/compose) for service orchestration
  - [GitHub Actions](https://github.com/features/actions) for CI/CD automation
  - [Nginx](https://nginx.org) as reverse proxy and SSL termination
  - [Let's Encrypt](https://letsencrypt.org) for SSL certificates

## Project Structure

```text
|── .github/workflows/      # CI/CD workflows
├── backend/                # Go backend services
│   ├── cmd/server/         # Application entry point
│   ├── internal/           # Private application code
│   └── pkg/                # Shared packages
├── docker/                 # Docker configuration files
├── frontend/               # Astro application
│   ├── public/             # Static assets
│   └── src/                # Source code
│       ├── components/     # UI components
│       ├── content/        # Markdown/MDX content
│       ├── layouts/        # Page templates
│       └── pages/          # Route definitions
├── scripts/                # Utility scripts
└── .env.dev               # Development environment variables
```

## Getting Started

### Requirements

- Node.js 18.0.0+
- npm 6.0.0+
- Docker and Docker Compose (for containerized development)
- Go 1.18+ (for backend development)

### Initial Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/username/mlorente.dev.git
   cd mlorente.dev
   ```

2. Setup development environment:

   ```bash
   # Configure development environment
   ./scripts/setup-env.sh
   ```

### Development Workflow

#### Containerized Development (Recommended)

```bash
# Start all services
docker compose -f docker-compose.dev.yml up

# View logs
docker compose -f docker-compose.dev.yml logs -f [service_name]

# Stop all services
docker compose -f docker-compose.dev.yml down
```

Containerized development provides:

- Frontend at <http://localhost:3000>
- Backend at <http://localhost:8080>
- Hot reloading for both frontend and backend
- Consistent logging and error handling

#### Individual Component Development

**Frontend**:

```bash
cd frontend
npm install
npm run dev
```

**Backend**:

```bash
cd backend
go mod download
go mod tidy
go run cmd/server/main.go
```

For hot reloading with Go:

```bash
go install github.com/air-verse/air@latest
export PATH=$(go env GOPATH)/bin:$PATH
air
```

## API Endpoints

The backend exposes these RESTful endpoints to support the frontend application:

- **`/api/subscribe`**:
  - **Method**: POST
  - **Purpose**: Register a new email for newsletter subscription
  - **Request Body**: `{ "email": "user@example.com", "tags": ["tag1", "tag2"], "utmSource": "source" }`
  - **Response**: Subscription confirmation with subscriber ID

- **`/api/unsubscribe`**:
  - **Methods**: POST, GET
  - **Purpose**: Remove an email from newsletter subscriptions
  - **Request Body** (POST): `{ "email": "user@example.com" }`
  - **Query Params** (GET): `?email=user@example.com`
  - **Response**: Confirmation of unsubscription

- **`/api/lead-magnet`**:
  - **Method**: POST
  - **Purpose**: Subscribe user and send a resource (lead magnet)
  - **Request Body**: `{ "email": "user@example.com", "resourceId": "id", "fileId": "file", "tags": ["tag1"] }`
  - **Response**: Confirmation of subscription and resource delivery

- **`/api/resource-email`**:
  - **Method**: POST
  - **Purpose**: Send an email with resource to existing subscriber
  - **Request Body**: `{ "email": "user@example.com", "resourceId": "id", "resourceLink": "url" }`
  - **Response**: Confirmation of email delivery

These endpoints utilize HTMX-compatible responses, allowing for seamless frontend integration without complex JavaScript.

## Deployment

### CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment with separate workflows for frontend and backend:

#### Frontend CI Workflow

- **Trigger**: Changes to `/frontend` or workflow files
- **Steps**:
  1. Checkout code
  2. Setup Node.js environment
  3. Install dependencies
  4. Run linting and type checking
  5. Execute tests
  6. Build the application
  7. Create and push Docker image

#### Backend CI Workflow

- **Trigger**: Changes to `/backend` or workflow files
- **Steps**:
  1. Checkout code
  2. Setup Go environment
  3. Install dependencies
  4. Run `go vet` for static analysis
  5. Execute tests
  6. Build the application
  7. Create and push Docker image

#### Deploy Workflow

- **Trigger**:
  - Completion of CI workflows
  - Manual trigger from GitHub UI
  - Repository dispatch event
- **Environment Selection**:
  - `master` branch → Production (`mlorente.dev`)
  - `feature/*` or `hotfix/*` branches → Staging (`staging.mlorente.dev`)
- **Steps**:
  1. Connect to server via SSH
  2. Update configuration
  3. Pull latest Docker images
  4. Apply database migrations (if needed)
  5. Restart services
  6. Run health checks

### Branch Strategy

- **`master`**: Production-ready code, deployed to production
- **`develop`**: Integration branch for feature development
- **`feature/*`**: Isolated feature development, merged to develop
- **`hotfix/*`**: Urgent fixes applied directly to master and develop

### Deployment Environments

| Environment | URL | Purpose | Access |
|-------------|-----|---------|--------|
| Production | mlorente.dev | Live site | Public |
| Staging | staging.mlorente.dev | Pre-release testing | Private |

### Manual Deployment

For situations where CI/CD is not suitable, manual deployment is possible:

```bash
# Deploy to production
./scripts/deploy.sh production

# Deploy to staging
./scripts/deploy.sh staging

# Direct deployment on production server
cd /opt/mlorente
docker-compose pull
docker-compose up -d
```

### Deployment Verification

After deployment, automatic health checks verify the application status:

```bash
# Check application health
./scripts/health-check.sh production

# View deployment logs
./scripts/deployment-logs.sh production
```

## Infrastructure

### Hosting Environment

The application is hosted on Hetzner Cloud with the following specifications:

#### Production Server

- **Hostname**: `mlorente.dev`
- **Server Type**: Hetzner CX41 (4 vCPU, 16GB RAM)
- **Location**: Falkenstein, Germany (EU-central)
- **Operating System**: Ubuntu 22.04 LTS
- **Firewall**: UFW with restricted access
- **Monitoring**: Node Exporter + Prometheus

#### Staging Server

- **Hostname**: `staging.mlorente.dev`
- **Server Type**: Hetzner CX21 (2 vCPU, 4GB RAM)
- **Location**: Falkenstein, Germany (EU-central)
- **Operating System**: Ubuntu 22.04 LTS
- **Firewall**: UFW with restricted access

### Server Setup

Each server is configured using the `setup-server.sh` script, which:

1. Updates the system
2. Installs Docker and Docker Compose
3. Configures firewall rules
4. Sets up fail2ban for SSH protection
5. Creates a non-root deployment user
6. Configures automatic security updates
7. Sets up Let's Encrypt certificates

### Docker Images

Docker images are stored on DockerHub with the following versioning scheme:

#### Frontend Images

- `mlorentedev/mlorente-frontend:latest` - Production version (master branch)
- `mlorentedev/mlorente-frontend:develop` - Development version
- `mlorentedev/mlorente-frontend:[commit-hash]` - Specific commit version
- `mlorentedev/mlorente-frontend:feature-*` - Feature branch versions

#### Backend Images

- `mlorentedev/mlorente-backend:latest` - Production version (master branch)
- `mlorentedev/mlorente-backend:develop` - Development version
- `mlorentedev/mlorente-backend:[commit-hash]` - Specific commit version
- `mlorentedev/mlorente-backend:feature-*` - Feature branch versions

### Network Architecture

```text
                   ┌─────────────┐
                   │    Nginx    │
                   │Reverse Proxy│
                   └──────┬──────┘
                          │
                          ▼
          ┌───────────────┴───────────────┐
          │                               │
┌─────────▼──────────┐       ┌────────────▼─────────┐
│                    │       │                      │
│  Frontend (Astro)  │       │   Backend (Go API)   │
│                    │       │                      │
└────────────────────┘       └──────────────────────┘
```

All services run as Docker containers orchestrated with Docker Compose, with Nginx serving as the entry point and handling SSL termination.

## Troubleshooting

### Common Issues and Solutions

#### Application Not Responding

If the application is not responding, first check the container status:

```bash
docker-compose ps
```

Look for containers in an unhealthy state or containers that have restarted multiple times. If needed, restart services:

```bash
docker-compose restart
```

#### Frontend Errors

For issues with the frontend application:

```bash
docker-compose logs frontend
```

Common frontend issues include:

- Missing environment variables
- Build failures due to syntax errors
- Static asset loading problems
- CORS issues when communicating with the backend

#### Backend Errors

For backend service issues:

```bash
docker-compose logs backend
```

Common backend issues include:

- Database connection failures
- API validation errors
- External service integration problems
- Resource constraints (memory/CPU)

#### SSL Certificate Issues

If experiencing SSL errors:

```bash
# Check certificate status
docker-compose exec nginx openssl x509 -in /etc/letsencrypt/live/mlorente.dev/fullchain.pem -text -noout

# Restart certbot to attempt renewal
docker-compose restart certbot
```

#### Deployment Failures

If a deployment fails or introduces issues:

```bash
# List available versions
./scripts/rollback.sh production list

# Roll back to a specific version
./scripts/rollback.sh production v1.2.3
```

#### Environment Variable Problems

If environment variables are missing or incorrect:

```bash
# Update environment variables
./scripts/update-env.sh production
```

## Advanced Operations

The project includes utility scripts for maintenance and operational tasks:

### Performance Testing

Test the performance of individual endpoints or the entire application:

```bash
# Test performance of all endpoints in production
./scripts/monitor-performance.sh production

# Test specific endpoint with 1000 requests and 50 concurrent users
./scripts/monitor-performance.sh production /api/subscribe 1000 50

# Compare performance between environments
./scripts/monitor-performance.sh compare production staging
```

The performance testing script uses `wrk` under the hood and provides metrics on:

- Requests per second
- Average response time
- P95/P99 response times
- Error rates

### Security Verification

Verify security configuration and identify potential vulnerabilities:

```bash
# Comprehensive security scan of production environment
./scripts/monitor-security.sh production

# Check specific aspect (ssl, headers, firewall, etc.)
./scripts/monitor-security.sh production ssl

# Generate a detailed security report
./scripts/monitor-security.sh production --report
```

The security check includes:

- SSL configuration and certificate validation
- HTTP security headers
- Firewall rule verification
- Open port scanning
- Docker configuration best practices

### Log Analysis

Analyze application logs to identify issues or patterns:

```bash
# Analyze all service logs in production
./scripts/monitor-logs.sh production

# Analyze specific service logs
./scripts/monitor-logs.sh production nginx

# Focus on errors only
./scripts/monitor-logs.sh production --errors-only

# Analyze logs within a time period
./scripts/monitor-logs.sh production --since "2023-01-01" --until "2023-01-02"
```

The log analysis provides:

- Error frequency and patterns
- Request path analysis
- Performance bottlenecks
- User behavior insights
- Anomaly detection

## Additional Resources

- [CONTRIBUTING.md](CONTRIBUTING.md): Contribution guidelines
- [LICENSE](LICENSE): MIT License information
- [scripts/README.md](scripts/README.md): Documentation for utility scripts
