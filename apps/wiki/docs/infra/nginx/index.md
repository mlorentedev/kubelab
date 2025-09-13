# 2.2 Nginx - Static Web Server

Lightweight and efficient web server for serving static content, custom error pages, and acting as a backend for the Traefik reverse proxy.

## What it is

This Nginx service handles static content delivery and provides custom error pages for the mlorente.dev ecosystem. It serves as a fallback backend behind Traefik, delivering maintenance pages, error responses, and any static assets that don't belong to specific applications. I use it because it's incredibly efficient at serving static files and has minimal resource usage.

## Tech stack

- **Nginx Alpine** - Lightweight Docker image optimized for size
- **Static content** - HTML, CSS, JS, and media files
- **Custom error pages** - Branded 404, 500, maintenance pages
- **High performance** - Optimized for concurrent connections

## Project structure

```
infra/nginx/
├── README.md              # This documentation
├── docker-compose.yml     # Nginx service configuration
├── nginx.conf            # Main Nginx configuration
├── conf.d/               # Additional configuration files
│   ├── default.conf      # Default server configuration
│   └── gzip.conf        # Compression settings
├── html/                 # Static content
│   ├── index.html       # Default landing page
│   ├── 404.html         # Custom 404 error page
│   ├── 500.html         # Server error page
│   ├── maintenance.html # Maintenance mode page
│   └── assets/          # CSS, JS, images
└── logs/                # Access and error logs
```

## Key features

### Static content serving
- **High performance** - Optimized for serving static files
- **Compression** - Gzip compression for all text content
- **Caching** - Proper cache headers for static assets
- **Security headers** - Basic security headers for protection

### Error handling
- **Custom error pages** - Branded 404, 500, and maintenance pages
- **Graceful fallbacks** - Clean error responses when services are down
- **Maintenance mode** - Easy maintenance page activation

### Integration
- **Traefik backend** - Seamless integration with reverse proxy
- **Docker networking** - Shared network with other services
- **Hot reload** - Configuration changes without restart

## Configuration

### Basic Nginx configuration (nginx.conf)

```nginx
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    # Performance optimizations
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 16M;

    # Gzip compression
    include /etc/nginx/conf.d/gzip.conf;
    
    # Server configurations
    include /etc/nginx/conf.d/*.conf;
}
```

### Default server configuration (conf.d/default.conf)

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Static assets caching
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # Main content
    location / {
        try_files $uri $uri/ =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # Custom error pages
    error_page 404 /404.html;
    error_page 500 502 503 504 /500.html;

    location = /404.html {
        internal;
    }

    location = /500.html {
        internal;
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Deny access to hidden files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

### Compression settings (conf.d/gzip.conf)

```nginx
# Gzip compression
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_proxied any;
gzip_comp_level 6;
gzip_types
    text/plain
    text/css
    text/xml
    text/javascript
    application/javascript
    application/xml+rss
    application/json
    application/xml
    image/svg+xml;
```

## Running Nginx

### Development setup

```bash
# Start Nginx service
make up-nginx

# Access static content
open http://nginx.mlorentedev.test

# Check health endpoint
curl http://nginx.mlorentedev.test/health
```

### Docker configuration

```yaml
services:
  nginx:
    image: nginx:alpine
    container_name: static-nginx
    restart: unless-stopped
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./conf.d:/etc/nginx/conf.d:ro
      - ./html:/usr/share/nginx/html:ro
      - ./logs:/var/log/nginx
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.nginx.rule=Host(`static.mlorente.dev`)"
      - "traefik.http.routers.nginx.entrypoints=websecure"
      - "traefik.http.routers.nginx.tls=true"
      - "traefik.http.routers.nginx.tls.certresolver=letsencrypt"
      - "traefik.http.services.nginx.loadbalancer.server.port=80"

networks:
  proxy:
    external: true
```

## Error pages

### Custom 404 page (html/404.html)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Not Found - mlorente.dev</title>
    <link rel="stylesheet" href="/assets/css/error.css">
</head>
<body>
    <div class="error-container">
        <div class="error-code">404</div>
        <div class="error-message">Page Not Found</div>
        <div class="error-description">
            The page you're looking for doesn't exist or has been moved.
        </div>
        <div class="error-actions">
            <a href="/" class="btn-primary">Go Home</a>
            <a href="/blog" class="btn-secondary">Visit Blog</a>
        </div>
    </div>
</body>
</html>
```

### Maintenance page (html/maintenance.html)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maintenance - mlorente.dev</title>
    <link rel="stylesheet" href="/assets/css/maintenance.css">
    <meta http-equiv="refresh" content="300">
</head>
<body>
    <div class="maintenance-container">
        <div class="maintenance-icon">🔧</div>
        <div class="maintenance-title">Under Maintenance</div>
        <div class="maintenance-message">
            We're currently performing scheduled maintenance to improve your experience.
            Please check back in a few minutes.
        </div>
        <div class="maintenance-eta">
            Estimated completion: <span id="eta">15 minutes</span>
        </div>
    </div>
</body>
</html>
```

## Monitoring

### Health checks

```bash
# Basic health check
curl -f http://nginx.mlorentedev.test/health

# Check response headers
curl -I http://nginx.mlorentedev.test/

# Test static assets
curl -I http://nginx.mlorentedev.test/assets/css/style.css
```

### Logs monitoring

```bash
# Follow access logs
tail -f logs/access.log

# Follow error logs
tail -f logs/error.log

# Check log rotation
ls -la logs/

# Parse access logs for analytics
grep "GET /" logs/access.log | wc -l
```

### Performance testing

```bash
# Simple load test with curl
for i in {1..100}; do
  curl -s -o /dev/null http://nginx.mlorentedev.test/
done

# Test compression
curl -H "Accept-Encoding: gzip" -I http://nginx.mlorentedev.test/

# Test caching headers
curl -I http://nginx.mlorentedev.test/assets/css/style.css
```

## Maintenance mode

### Enable maintenance mode

```bash
# Redirect all traffic to maintenance page
cat > conf.d/maintenance.conf << EOF
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    
    location / {
        return 503;
    }
    
    error_page 503 /maintenance.html;
    location = /maintenance.html {
        internal;
    }
    
    # Keep health check active
    location /health {
        return 200 "maintenance\n";
        add_header Content-Type text/plain;
    }
}
EOF

# Reload Nginx configuration
docker-compose exec nginx nginx -s reload
```

### Disable maintenance mode

```bash
# Remove maintenance configuration
rm conf.d/maintenance.conf

# Reload Nginx configuration
docker-compose exec nginx nginx -s reload
```

## Security

### Basic security measures

```nginx
# Hide Nginx version
server_tokens off;

# Deny access to sensitive files
location ~ /\.(ht|git|svn) {
    deny all;
    access_log off;
    log_not_found off;
}

# Limit request size
client_max_body_size 16M;

# Rate limiting (if needed)
limit_req_zone $binary_remote_addr zone=static:10m rate=10r/s;
limit_req zone=static burst=20 nodelay;
```

### SSL/TLS considerations

Since Nginx runs behind Traefik, SSL is handled at the proxy level:
- **No direct SSL** - Traefik handles all TLS termination
- **HTTP only** - Internal communication is unencrypted
- **Trusted proxy** - Nginx trusts headers from Traefik
- **Secure cookies** - Set secure flags when behind HTTPS proxy

## Troubleshooting

### Common issues

**Static files not loading:**
1. Check file permissions in html/ directory
2. Verify volume mounts in docker-compose.yml
3. Check Nginx error logs for access issues
4. Ensure files exist in the correct location

**Configuration errors:**
1. Test configuration: `docker-compose exec nginx nginx -t`
2. Check syntax in .conf files
3. Review error logs for specific issues
4. Restart container after changes

**Performance issues:**
1. Monitor connection limits
2. Check file sizes and compression
3. Review access patterns in logs
4. Consider adjusting worker processes

### Debug commands

```bash
# Test Nginx configuration
docker-compose exec nginx nginx -t

# Reload configuration
docker-compose exec nginx nginx -s reload

# Check active connections
docker-compose exec nginx nginx -s status

# Verify file permissions
docker-compose exec nginx ls -la /usr/share/nginx/html/
```

## Local development URLs

When running locally with `make up-nginx`:
- Static site: http://nginx.mlorentedev.test
- Health check: http://nginx.mlorentedev.test/health
- Error pages: http://nginx.mlorentedev.test/404.html

Add `127.0.0.1 nginx.mlorentedev.test` to your `/etc/hosts` file for local domain access.

## Use cases

- **Error page serving** - Custom 404/500 pages for the entire ecosystem
- **Maintenance pages** - Temporary maintenance notifications
- **Static assets** - Serving shared CSS, JS, and image files
- **Landing pages** - Simple static landing or coming soon pages
- **Health monitoring** - Basic health endpoint for load balancers