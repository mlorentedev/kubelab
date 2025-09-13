# 2.1 Traefik - Reverse Proxy

Modern reverse proxy and load balancer that simplifies microservice deployment with automatic service discovery, TLS termination, and dynamic routing.

## What it is

Traefik handles all incoming traffic to the mlorente.dev ecosystem. It automatically discovers services through Docker labels, manages SSL certificates with Let's Encrypt, and routes requests to the appropriate applications. I chose Traefik because it eliminates the need for manual configuration - just label your containers and it figures out the rest.

## Tech stack

- **Traefik v3.0** - Modern reverse proxy with HTTP/3 support
- **Let's Encrypt** - Automatic SSL certificate management
- **Docker integration** - Service discovery via Docker labels
- **Dynamic configuration** - Hot reload without restarts

## Project structure

```
infra/traefik/
├── README.md              # This documentation
├── docker-compose.yml     # Traefik service configuration
├── traefik.yml           # Static configuration
├── .env                  # Environment variables
├── certs/                # SSL certificates
│   └── acme.json         # Let's Encrypt certificates
├── dynamic/              # Dynamic configurations
│   ├── middlewares.yml   # Global middlewares
│   └── tls.yml          # TLS configuration
└── logs/                # Access and error logs
```

## Key features

### Service discovery
- **Docker labels** - Automatic service detection
- **File provider** - Static configuration files
- **Hot reload** - Configuration updates without restart

### SSL management
- **Let's Encrypt** - Automatic certificate generation and renewal
- **HTTP to HTTPS** - Automatic redirects
- **Modern TLS** - TLS 1.2+ with secure cipher suites

### Load balancing
- **Health checks** - Automatic backend monitoring
- **Multiple algorithms** - Round robin, weighted, sticky sessions
- **Circuit breaker** - Fault tolerance and cascade protection

## Configuration

### Environment variables

```bash
# Basic configuration
TRAEFIK_DOMAIN=mlorente.dev
TRAEFIK_EMAIL=admin@mlorente.dev
LETS_ENCRYPT_EMAIL=letsencrypt@mlorente.dev

# Let's Encrypt server
ACME_CA_SERVER=https://acme-v02.api.letsencrypt.org/directory

# Dashboard security
TRAEFIK_DASHBOARD_AUTH=admin:$2y$10$hashed_password

# Logging
LOG_LEVEL=INFO
ACCESS_LOG_FORMAT=json

# Docker network
DOCKER_NETWORK=proxy
```

### Static configuration (traefik.yml)

```yaml
# API and dashboard
api:
  dashboard: true
  debug: false

# Health check endpoint
ping: {}

# Logging
log:
  level: INFO
  filePath: /logs/traefik.log

accessLog:
  filePath: /logs/access.log
  format: json

# Entry points
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
      email: letsencrypt@mlorente.dev
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

# Global settings
global:
  checkNewVersion: false
  sendAnonymousUsage: false
```

## Running Traefik

### Development setup

```bash
# Create network
docker network create proxy

# Create directories
mkdir -p certs logs dynamic

# Set certificate permissions
touch certs/acme.json
chmod 600 certs/acme.json

# Start Traefik
make up-traefik

# Access dashboard
open http://traefik.mlorentedev.test
```

### Production deployment

```bash
# Configure production environment
cp .env.example .env
# Edit .env with production values

# Generate basic auth password
htpasswd -nb admin your-secure-password

# Deploy
docker-compose up -d

# Monitor logs
docker-compose logs -f traefik
```

## Service configuration

### Basic service with HTTPS

```yaml
services:
  app:
    image: nginx:alpine
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.mlorente.dev`)"
      - "traefik.http.routers.app.entrypoints=websecure"
      - "traefik.http.routers.app.tls=true"
      - "traefik.http.routers.app.tls.certresolver=letsencrypt"
      - "traefik.http.services.app.loadbalancer.server.port=80"

networks:
  proxy:
    external: true
```

### API service with middlewares

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.api.rule=Host(`api.mlorente.dev`)"
  - "traefik.http.routers.api.entrypoints=websecure"
  - "traefik.http.routers.api.tls=true"
  - "traefik.http.routers.api.tls.certresolver=letsencrypt"
  - "traefik.http.routers.api.middlewares=api-cors,api-ratelimit"
  - "traefik.http.services.api.loadbalancer.server.port=8080"
  
  # CORS middleware
  - "traefik.http.middlewares.api-cors.headers.accesscontrolalloworiginlist=https://mlorente.dev"
  - "traefik.http.middlewares.api-cors.headers.accesscontrolallowheaders=Content-Type,Authorization"
  
  # Rate limiting
  - "traefik.http.middlewares.api-ratelimit.ratelimit.average=100"
  - "traefik.http.middlewares.api-ratelimit.ratelimit.period=60s"
```

## Middlewares

### Security headers (dynamic/middlewares.yml)

```yaml
http:
  middlewares:
    secure-headers:
      headers:
        customResponseHeaders:
          X-Frame-Options: "DENY"
          X-Content-Type-Options: "nosniff"
          X-XSS-Protection: "1; mode=block"
          Strict-Transport-Security: "max-age=31536000; includeSubDomains"
          Referrer-Policy: "strict-origin-when-cross-origin"

    gzip-compress:
      compress: {}

    rate-limit:
      rateLimit:
        burst: 100
        period: 10s
```

## Monitoring

### Dashboard access

- **URL**: https://traefik.mlorente.dev
- **Authentication**: Basic auth (configured in .env)
- **Features**: Real-time service status, traffic metrics, configuration overview

### Health checks

```bash
# Basic health check
curl -f http://localhost:8080/ping

# API status
curl -s http://localhost:8080/api/version

# Service status
curl -s http://localhost:8080/api/http/services | jq

# Check SSL certificate
curl -I https://mlorente.dev
```

### Logs

```bash
# Follow logs
docker-compose logs -f traefik

# Access logs
tail -f logs/access.log

# Error logs
tail -f logs/traefik.log
```

## Troubleshooting

### Common issues

**Service not accessible:**
1. Check if service is in proxy network
2. Verify Docker labels are correct
3. Check Traefik logs for errors
4. Ensure domain DNS points to server

**SSL certificate issues:**
1. Verify Let's Encrypt rate limits
2. Check domain ownership
3. Review ACME challenge logs
4. Ensure ports 80/443 are accessible

**Dashboard not loading:**
1. Verify basic auth credentials
2. Check Traefik container is running
3. Ensure port 8080 is accessible
4. Review dashboard router configuration

### Debug commands

```bash
# Check Traefik configuration
docker-compose exec traefik traefik config

# Test service connectivity
docker-compose exec traefik ping app

# Validate certificates
openssl s_client -connect mlorente.dev:443 -servername mlorente.dev

# Check network connectivity
docker network inspect proxy
```

## Local development URLs

When running locally with `make up-traefik`:
- Dashboard: http://traefik.mlorentedev.test
- API: http://localhost:8080/api/
- Ping: http://localhost:8080/ping

Add `127.0.0.1 traefik.mlorentedev.test` to your `/etc/hosts` file for local domain access.

## Security considerations

- **Dashboard protection**: Always use basic auth or IP restrictions
- **Certificate storage**: Secure acme.json file permissions (600)
- **Network isolation**: Use dedicated Docker network for services
- **Log monitoring**: Monitor access logs for suspicious activity
- **Regular updates**: Keep Traefik updated to latest stable version