# 1.5 Portainer - Docker Management

Web interface for Docker management that provides complete administration of containers, images, networks, and volumes with an intuitive GUI for Docker environments.

## What it is

Portainer gives me a clean web interface to manage all Docker containers across the mlorente.dev infrastructure. Instead of using command-line docker commands for everything, I can visually monitor, start, stop, and configure containers. It's especially useful for quick troubleshooting and monitoring resource usage.

## Tech stack

- **Portainer CE** - Community Edition with all essential features
- **Docker Socket** - Direct access to Docker daemon
- **Web UI** - Clean, responsive management interface
- **Real-time monitoring** - Live container stats and logs

## Key features

### Container management
- **Visual interface** - See all containers at a glance
- **Start/stop/restart** - One-click container control
- **Log viewing** - Real-time and historical logs
- **Resource monitoring** - CPU, memory, and network usage

### Image management
- **Image browser** - View all local and registry images
- **Pull images** - Download new images from registries
- **Build images** - Build from Dockerfile through UI
- **Image cleanup** - Remove unused images easily

### System monitoring
- **Dashboard overview** - System stats and container health
- **Network inspection** - View Docker networks and connections
- **Volume management** - Handle persistent data storage
- **Stack deployment** - Deploy docker-compose stacks

## Configuration

### Docker Compose setup

```yaml
services:
  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: unless-stopped
    ports:
      - "9000:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - portainer_data:/data
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.portainer.rule=Host(`portainer.mlorente.dev`)"
      - "traefik.http.routers.portainer.entrypoints=websecure"
      - "traefik.http.routers.portainer.tls=true"
      - "traefik.http.routers.portainer.tls.certresolver=letsencrypt"
      - "traefik.http.services.portainer.loadbalancer.server.port=9000"

volumes:
  portainer_data:

networks:
  proxy:
    external: true
```

## Running Portainer

### Development setup

```bash
# Start Portainer
make up-portainer

# Access web interface
open http://portainer.mlorentedev.test
```

### First-time setup

1. **Access interface**: Navigate to Portainer URL
2. **Create admin user**: Set username and password
3. **Select environment**: Choose local Docker environment
4. **Start managing**: Begin container management

### Security considerations

- **Read-only socket**: Docker socket mounted as read-only for security
- **Admin access**: Restrict admin credentials carefully
- **HTTPS only**: Always use SSL in production
- **Regular updates**: Keep Portainer updated to latest version

## Common tasks

### Monitor container health

```bash
# Through Portainer UI:
# 1. Go to Containers page
# 2. Check status indicators
# 3. Click container for detailed stats
# 4. View real-time resource usage
```

### View container logs

```bash
# Through Portainer UI:
# 1. Click on container name
# 2. Go to Logs tab
# 3. View real-time or historical logs
# 4. Download logs if needed
```

### Deploy new containers

```bash
# Through Portainer UI:
# 1. Go to Containers > Add container
# 2. Configure image and settings
# 3. Set environment variables
# 4. Configure networks and volumes
# 5. Deploy container
```

## Integration with ecosystem

### Works with Traefik
- **Service discovery** - Portainer appears in Traefik dashboard
- **SSL termination** - HTTPS handled by Traefik
- **Load balancing** - Integrated with proxy network

### Monitors all services
- **API containers** - Go backend monitoring
- **Web containers** - Astro frontend status
- **Blog containers** - Jekyll site monitoring
- **Wiki containers** - MkDocs documentation
- **Infrastructure** - Traefik, databases, monitoring tools

## Troubleshooting

### Cannot access Portainer
1. Check if container is running: `docker ps | grep portainer`
2. Verify port mapping: `docker port portainer`
3. Check Traefik routing: Look at Traefik dashboard
4. Verify network connectivity: `curl http://localhost:9000`

### Docker socket permissions
1. Ensure Docker socket is mounted: `docker exec portainer ls -la /var/run/docker.sock`
2. Check container logs: `docker logs portainer`
3. Verify user permissions: Current user should be in docker group

### UI not loading
1. Clear browser cache and cookies
2. Check browser console for JavaScript errors
3. Try different browser or incognito mode
4. Verify SSL certificate if using HTTPS

## Local development URLs

When running locally with `make up-portainer`:
- **Web Interface**: http://portainer.mlorentedev.test
- **Direct access**: http://localhost:9000
- **API endpoint**: http://portainer.mlorentedev.test/api/

Add `127.0.0.1 portainer.mlorentedev.test` to your `/etc/hosts` file.

## Best practices

- **Regular backups** - Export Portainer configuration regularly
- **Resource monitoring** - Use Portainer to monitor container resource usage
- **Security updates** - Keep Portainer image updated
- **Access control** - Use strong passwords and limit admin access
- **Log management** - Regularly review container logs for issues

Portainer makes Docker management much more visual and user-friendly, especially when you need to quickly check container status or troubleshoot issues without remembering complex docker commands.