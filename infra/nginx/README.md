# Nginx - Servidor Web Estático

Servidor web ligero y eficiente para servir contenido estático, páginas de error personalizadas y actuar como backend para el proxy reverso Traefik.

## 🏗️ Arquitectura

- **Imagen Base**: nginx:alpine (optimizada para tamaño reducido)
- **Propósito**: Servidor de contenido estático y páginas de error
- **Integración**: Backend para Traefik con red Docker compartida
- **Configuración**: Volúmenes montados para contenido personalizable
- **Performance**: Optimizado para alta concurrencia y bajo uso de memoria

## 📁 Estructura del Proyecto

```
infra/nginx/
├── README.md              # Esta documentación
├── docker-compose.yml     # Configuración del servicio
└── errors/               # Páginas de error personalizadas
    └── 404.html          # Página de error 404 personalizada
```

## 🚀 Características

### Servidor Web Ligero

- **Alto Rendimiento**: Nginx optimizado para servir contenido estático
- **Baja Latencia**: Respuesta rápida para archivos estáticos
- **Concurrencia**: Manejo eficiente de múltiples conexiones simultáneas
- **Compresión**: Compresión Gzip automática para archivos de texto
- **Caché**: Headers de caché optimizados para recursos estáticos

### Páginas de Error Personalizadas

- **404 Personalizado**: Página de error no encontrado con diseño custom
- **Branding**: Páginas de error alineadas con la identidad visual
- **Multiidioma**: Soporte para páginas de error en español
- **Responsive**: Diseño adaptable a diferentes dispositivos
- **SEO Friendly**: Códigos de estado HTTP correctos

### Integración con Traefik

- **Red Compartida**: Comunicación directa con Traefik via red `proxy`
- **Auto-descubrimiento**: Sin necesidad de configuración manual
- **SSL Passthrough**: Traefik maneja la terminación SSL
- **Load Balancing**: Capacidad de múltiples instancias
- **Health Checks**: Verificación automática de disponibilidad

## 🔧 Configuración

### Docker Compose

```yaml
services:
  nginx:
    image: nginx:alpine
    container_name: nginx
    volumes:
      - ./errors:/usr/share/nginx/html:ro
    networks:
      - proxy

networks:
  proxy:
    external: true
```

### Configuración de Volúmenes

El directorio `errors/` se monta como volumen de solo lectura:

```bash
# Estructura de contenido
errors/
├── 404.html          # Página de error 404
├── 500.html          # Página de error 500 (opcional)
├── 502.html          # Página de error 502 (opcional)
├── 503.html          # Página de error 503 (opcional)
├── assets/           # Recursos estáticos (CSS, JS, imágenes)
│   ├── css/
│   ├── js/
│   └── img/
└── favicon.ico       # Icono del sitio
```

### Configuración Nginx Personalizada

Para configuración avanzada, crear `nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;
    
    root /usr/share/nginx/html;
    index index.html;
    
    # Configuración de error pages
    error_page 404 /404.html;
    error_page 500 502 503 504 /50x.html;
    
    # Configuración de caché para assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Compresión Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    gzip_min_length 1000;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
}
```

## 🐳 Despliegue Docker

### Despliegue Básico

```bash
# Navegar al directorio
cd infra/nginx

# Crear red proxy si no existe
docker network create proxy

# Iniciar el servicio
docker-compose up -d

# Verificar que está ejecutándose
docker-compose ps
```

### Despliegue con Traefik

```yaml
# Configuración completa con labels de Traefik
services:
  nginx:
    image: nginx:alpine
    container_name: nginx
    volumes:
      - ./errors:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.nginx.rule=Host(`static.tudominio.com`)"
      - "traefik.http.routers.nginx.entrypoints=websecure"
      - "traefik.http.routers.nginx.tls=true"
      - "traefik.http.routers.nginx.tls.certresolver=letsencrypt"
      - "traefik.http.services.nginx.loadbalancer.server.port=80"

networks:
  proxy:
    external: true
```

### Verificación del Despliegue

```bash
# Verificar estado del contenedor
docker ps | grep nginx

# Ver logs
docker-compose logs nginx

# Probar conectividad
curl -I http://localhost

# Verificar página 404
curl -I http://localhost/pagina-inexistente
```

## 🛠️ Desarrollo Local

### Setup de Desarrollo

```bash
# Clonar el repositorio
cd infra/nginx

# Crear contenido de prueba
echo "<h1>Servidor Nginx funcionando</h1>" > errors/index.html

# Iniciar en modo desarrollo
docker-compose up

# Acceder en: http://localhost:80
```

### Personalización de Páginas de Error

```html
<!-- errors/404.html -->
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 - Página no encontrada</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            padding: 2rem;
            margin: 0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        
        h1 {
            font-size: 4rem;
            margin-bottom: 1rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        p {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            opacity: 0.9;
        }
        
        .btn {
            display: inline-block;
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 1rem 2rem;
            text-decoration: none;
            border-radius: 50px;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }
        
        .btn:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-2px);
        }
        
        @media (max-width: 768px) {
            h1 { font-size: 2.5rem; }
            p { font-size: 1rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚫 404</h1>
        <p>Lo sentimos, la página que buscas no pudo ser encontrada.</p>
        <a href="/" class="btn">🏠 Volver al inicio</a>
    </div>
</body>
</html>
```

### Testing de Páginas de Error

```bash
# Probar diferentes códigos de error
curl -w "%{http_code}" http://localhost/no-existe

# Verificar headers de respuesta
curl -I http://localhost/404

# Test de compresión
curl -H "Accept-Encoding: gzip" -I http://localhost/

# Verificar caché headers
curl -I http://localhost/style.css
```

## 🔍 Monitoreo y Logging

### Logs de Nginx

```bash
# Ver logs en tiempo real
docker-compose logs -f nginx

# Ver logs de acceso
docker exec nginx tail -f /var/log/nginx/access.log

# Ver logs de error
docker exec nginx tail -f /var/log/nginx/error.log

# Logs con formato JSON (si configurado)
docker exec nginx cat /var/log/nginx/access.log | jq
```

### Métricas y Monitoreo

```nginx
# Configuración para métricas básicas
location /nginx_status {
    stub_status on;
    access_log off;
    allow 127.0.0.1;
    allow 172.18.0.0/16;  # Red Docker
    deny all;
}
```

### Health Checks

```bash
# Health check básico
curl -f http://localhost/

# Health check con timeout
curl --max-time 5 http://localhost/

# Verificar desde Traefik
curl -f http://nginx:80/ # Desde dentro de la red Docker
```

## 🚀 Optimización de Performance

### Configuración de Caché

```nginx
# Cache de archivos estáticos
location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
    access_log off;
}

# Cache de HTML con validación
location ~* \.(html|htm)$ {
    expires 1h;
    add_header Cache-Control "public, must-revalidate";
}
```

### Compresión Optimizada

```nginx
# Compresión Gzip avanzada
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types
    application/atom+xml
    application/javascript
    application/json
    application/rss+xml
    application/vnd.ms-fontobject
    application/x-font-ttf
    application/x-web-app-manifest+json
    application/xhtml+xml
    application/xml
    font/opentype
    image/svg+xml
    image/x-icon
    text/css
    text/plain
    text/x-component;
```

### Límites y Timeouts

```nginx
# Configuración de rendimiento
client_max_body_size 10m;
client_body_timeout 60s;
client_header_timeout 60s;
keepalive_timeout 65s;
send_timeout 60s;

# Worker processes optimización
worker_processes auto;
worker_connections 1024;
```

## 🔐 Seguridad

### Headers de Seguridad

```nginx
# Headers de seguridad obligatorios
add_header X-Frame-Options DENY always;
add_header X-Content-Type-Options nosniff always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# Content Security Policy
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';" always;
```

### Configuración SSL (con Traefik)

```nginx
# Headers para HTTPS (cuando Traefik maneja SSL)
location / {
    # Verificar que la conexión sea HTTPS
    if ($http_x_forwarded_proto != "https") {
        return 301 https://$server_name$request_uri;
    }
    
    # HSTS Header
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
}
```

### Rate Limiting

```nginx
# Rate limiting básico
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    
    server {
        location / {
            limit_req zone=api burst=20 nodelay;
        }
    }
}
```

## 🔧 Casos de Uso Comunes

### Servidor de Assets Estáticos

```yaml
# Para servir assets de aplicaciones
services:
  nginx-assets:
    image: nginx:alpine
    volumes:
      - ../web/dist:/usr/share/nginx/html:ro
      - ./nginx-assets.conf:/etc/nginx/conf.d/default.conf:ro
    labels:
      - "traefik.http.routers.assets.rule=Host(`assets.tudominio.com`)"
```

### Página de Mantenimiento

```html
<!-- maintenance.html -->
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Mantenimiento</title>
    <meta http-equiv="refresh" content="30">
</head>
<body>
    <h1>🔧 Sitio en mantenimiento</h1>
    <p>Estaremos de vuelta pronto. Esta página se actualiza automáticamente.</p>
</body>
</html>
```

### Proxy para APIs Legacy

```nginx
# Proxy para servicios que no usan Docker
upstream legacy_api {
    server 192.168.1.50:8000;
    server 192.168.1.51:8000 backup;
}

server {
    location /api/legacy/ {
        proxy_pass http://legacy_api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🤝 Contribución

1. Fork del repositorio
2. Crear rama de feature
3. Añadir páginas en `errors/`
4. Personalizar configuración Nginx
5. Probar localmente con Docker
6. Documentar cambios
7. Enviar pull request

### Guidelines de Desarrollo

- Usar diseño responsive para páginas de error
- Mantener páginas ligeras y rápidas de cargar
- Incluir navegación de vuelta al sitio principal
- Seguir estándares de accesibilidad web
- Optimizar imágenes y assets
- Usar semantic HTML5

## 🔗 Servicios Relacionados

- **Traefik**: `infra/traefik` - Proxy reverso que enruta a Nginx
- **Apps Frontend**: `apps/web`, `apps/blog` - Aplicaciones web principales  
- **Monitoreo**: `apps/monitoring` - Métricas de Nginx
- **Ansible**: `infra/ansible` - Automatización de despliegue

## 📖 Recursos Adicionales

- [Documentación Oficial de Nginx](https://nginx.org/en/docs/)
- [Nginx Alpine Docker Image](https://hub.docker.com/_/nginx)
- [Nginx Security Headers](https://securityheaders.com/)
- [Nginx Performance Tuning](https://www.nginx.com/blog/tuning-nginx/)