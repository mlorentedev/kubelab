# 1.8 Uptime Kuma - Service Monitoring

Self-hosted monitoring tool that tracks website uptime, response times, and sends alerts when services go down. Provides a clean status page for monitoring all mlorente.dev services.

## What it is

Uptime Kuma monitors all the services in the mlorente.dev ecosystem and alerts me when something goes wrong. It checks HTTP endpoints, measures response times, and provides a beautiful status page. I use it because it's simple, self-hosted, and gives me peace of mind that my services are running.

## Tech stack

- **Uptime Kuma** - Modern uptime monitoring solution
- **SQLite** - Built-in database for monitoring data
- **Node.js** - JavaScript runtime
- **Docker** - Containerized deployment

## Key features

- **Website monitoring** - HTTP/HTTPS endpoint checks
- **Response time tracking** - Measure and graph response times  
- **Status pages** - Public status pages for services
- **Multiple notification channels** - Email, Slack, Discord, webhooks
- **SSL certificate monitoring** - Track certificate expiration

## Configuration

### Docker Compose setup

```yaml
services:
  uptime-kuma:
    image: louislam/uptime-kuma:1
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    volumes:
      - uptime_data:/app/data
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.uptime.rule=Host(`uptime.mlorente.dev`)"
      - "traefik.http.routers.uptime.entrypoints=websecure"
      - "traefik.http.routers.uptime.tls=true"
      - "traefik.http.routers.uptime.tls.certresolver=letsencrypt"
      - "traefik.http.services.uptime.loadbalancer.server.port=3001"

volumes:
  uptime_data:

networks:
  proxy:
    external: true
```

## Running Uptime Kuma

### Development setup

```bash
# Start Uptime Kuma
make up-uptime

# Access web interface  
open http://uptime.mlorentedev.test

# Create admin account on first visit
```

## Monitored services

- **Main Website**: https://mlorente.dev
- **API**: https://api.mlorente.dev/health  
- **Blog**: https://blog.mlorente.dev
- **Wiki**: https://wiki.mlorente.dev
- **Traefik Dashboard**: https://traefik.mlorente.dev

## Local development URLs

When running locally with `make up-uptime`:
- **Uptime Kuma**: http://uptime.mlorentedev.test
- **Direct access**: http://localhost:3001

Add `127.0.0.1 uptime.mlorentedev.test` to your `/etc/hosts` file.