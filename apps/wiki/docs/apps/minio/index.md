# 1.10 MinIO - Object Storage

High-performance, S3-compatible object storage server for storing files, images, and static assets. Provides a reliable, scalable storage backend for the mlorente.dev ecosystem.

## What it is

MinIO serves as the object storage solution for the mlorente.dev infrastructure. It provides S3-compatible storage for file uploads, static assets, backups, and any other binary data that needs reliable storage. I use it because it's lightweight, compatible with AWS S3 APIs, and perfect for self-hosted environments.

## Tech stack

- **MinIO** - High-performance object storage server
- **S3 API** - AWS S3-compatible interface
- **Docker** - Containerized deployment
- **Web console** - Built-in administration interface

## Key features

### Object storage
- **S3 compatibility** - Works with existing S3 SDKs and tools
- **High performance** - Fast read/write operations
- **Data protection** - Erasure coding and bit-rot protection
- **Scalability** - Horizontal scaling support

### Management
- **Web console** - Easy-to-use administration interface
- **Access policies** - Fine-grained access control
- **Bucket management** - Create and manage storage buckets
- **Monitoring** - Built-in metrics and health checks

## Configuration

### Docker Compose setup

```yaml
services:
  minio:
    image: minio/minio:latest
    container_name: minio
    restart: unless-stopped
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=${MINIO_ROOT_USER}
      - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
      - MINIO_BROWSER_REDIRECT_URL=https://minio.mlorente.dev
    volumes:
      - minio_data:/data
    networks:
      - proxy
    command: server /data --console-address ":9001"
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.minio-api.rule=Host(`s3.mlorente.dev`)"
      - "traefik.http.routers.minio-api.entrypoints=websecure"
      - "traefik.http.routers.minio-api.tls=true"
      - "traefik.http.routers.minio-api.tls.certresolver=letsencrypt"
      - "traefik.http.routers.minio-api.service=minio-api"
      - "traefik.http.services.minio-api.loadbalancer.server.port=9000"
      
      - "traefik.http.routers.minio-console.rule=Host(`minio.mlorente.dev`)"
      - "traefik.http.routers.minio-console.entrypoints=websecure"
      - "traefik.http.routers.minio-console.tls=true"
      - "traefik.http.routers.minio-console.tls.certresolver=letsencrypt"
      - "traefik.http.routers.minio-console.service=minio-console"
      - "traefik.http.services.minio-console.loadbalancer.server.port=9001"

volumes:
  minio_data:

networks:
  proxy:
    external: true
```

### Environment variables

```bash
# MinIO credentials
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=your_secure_password_here

# Optional configurations
MINIO_REGION_NAME=us-east-1
MINIO_BROWSER=on
MINIO_DOMAIN=s3.mlorente.dev
```

## Running MinIO

### Development setup

```bash
# Start MinIO
make up-minio

# Access web console
open http://minio.mlorentedev.test

# Access S3 API
# Endpoint: http://s3.mlorentedev.test
```

### Initial setup

1. **Access console**: Navigate to MinIO console URL
2. **Login**: Use root credentials from environment variables
3. **Create buckets**: Set up buckets for different use cases
4. **Configure policies**: Set up access policies as needed

## Usage examples

### Creating buckets

```bash
# Using MinIO client (mc)
mc alias set local http://localhost:9000 admin password
mc mb local/images
mc mb local/backups
mc mb local/static-assets
```

### Uploading files

```bash
# Upload a file
mc cp /path/to/file.jpg local/images/

# Upload directory
mc cp --recursive /path/to/folder/ local/static-assets/

# Set public access
mc policy set public local/images
```

### API usage in applications

```javascript
// Node.js example with MinIO SDK
const Minio = require('minio');

const minioClient = new Minio.Client({
  endPoint: 'localhost',
  port: 9000,
  useSSL: false,
  accessKey: 'admin',
  secretKey: 'password'
});

// Upload file
await minioClient.putObject('images', 'photo.jpg', fileBuffer);

// Get file URL
const url = await minioClient.presignedGetObject('images', 'photo.jpg');
```

### Backup configurations

```bash
# Backup to MinIO
mc mirror /local/backup/path local/backups/daily/

# Restore from MinIO
mc mirror local/backups/daily/ /local/restore/path
```

## Integration with applications

### Static file serving
- **Blog images** - Store blog post images and assets
- **User uploads** - Handle file uploads from web applications
- **Media storage** - Store photos, documents, and media files

### Backup storage
- **Database backups** - Store PostgreSQL/MySQL dumps
- **Configuration backups** - Store Docker volumes and configs
- **Log archives** - Long-term log storage

## Troubleshooting

### Cannot access MinIO console
1. Check container status: `docker ps | grep minio`
2. Verify port mapping: `docker port minio`
3. Check logs: `docker logs minio`
4. Verify environment variables

### S3 API not responding
1. Confirm API port (9000) is accessible
2. Check network connectivity: `curl http://localhost:9000/minio/health/live`
3. Verify credentials and permissions
4. Review Traefik routing configuration

### Storage issues
1. Check disk space: `df -h`
2. Verify volume mounts: `docker exec minio ls -la /data`
3. Check file permissions: `docker exec minio ls -la /data`

## Local development URLs

When running locally with `make up-minio`:
- **MinIO Console**: http://minio.mlorentedev.test
- **S3 API Endpoint**: http://s3.mlorentedev.test
- **Direct console access**: http://localhost:9001
- **Direct API access**: http://localhost:9000

Add these to your `/etc/hosts` file:
```
127.0.0.1 minio.mlorentedev.test
127.0.0.1 s3.mlorentedev.test
```

## Best practices

- **Access control** - Use IAM policies for granular permissions
- **Bucket organization** - Create separate buckets for different use cases
- **Security** - Use strong credentials and enable HTTPS in production
- **Monitoring** - Monitor storage usage and performance metrics
- **Backup strategy** - Implement regular backup procedures

MinIO provides reliable, S3-compatible object storage that scales with your needs and integrates seamlessly with existing applications.