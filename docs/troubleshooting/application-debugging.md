---
id: "kubelab-troubleshooting-application-debugging"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Application Debugging

Troubleshooting KubeLab's custom applications: API (Go) and Web (Astro, source in its own repository since ADR-053).

## API (Go)

### API Not Responding

#### Problem

The Go API service is not responding to HTTP requests.

#### Diagnostic Steps

```bash
# Check API health endpoint
curl http://localhost:8080/health
curl https://api.kubelab.live/health

# View detailed logs
toolkit apps logs api -f

# Check Go runtime metrics
curl http://localhost:8080/debug/vars   # If expvar enabled

# Verify database connectivity
docker exec api-container go run ./cmd/healthcheck
```

#### Solution

- Check logs for panic/fatal errors
- Verify all required environment variables are set
- Restart the API container: `toolkit apps restart api`

### Build Failures

#### Problem

Go application fails to compile or build Docker image.

#### Diagnostic Steps

```bash
# Check for compilation errors
cd apps/api/src
go test ./...
go vet ./...
```

#### Solution

```bash
# Clear Go cache
docker exec api-container go clean -cache -modcache

# Verify dependencies
docker exec api-container go mod verify
docker exec api-container go mod tidy
```

#### Prevention

- Run `go vet` and `go test` in CI before building images
- Keep `go.sum` committed and up to date

### Memory Leaks

#### Problem

API container memory usage grows unbounded over time.

#### Diagnostic Steps

```bash
# Enable pprof (if configured)
curl http://localhost:8080/debug/pprof/heap > heap.prof
go tools pprof -http=:9090 heap.prof

# Check goroutine leaks
curl http://localhost:8080/debug/pprof/goroutine?debug=2

# Monitor container memory
docker stats api-container
```

#### Solution

- Analyze heap profile for allocation hotspots
- Check for goroutine leaks (unclosed channels, missing context cancellation)
- Review database connection pool settings

#### Prevention

- Integrate pprof endpoints in non-production builds
- Set `GOMEMLIMIT` to 90% of container memory limit
- Use `context.Context` with timeouts for all I/O operations

## Web (Astro)

### Build Failures

#### Problem

Astro site fails to build.

#### Diagnostic Steps

```bash
# Check Node version
docker exec web-container node --version

# Build locally
cd apps/web/site
npm run build

# Check for TypeScript errors
npm run check
```

#### Solution

```bash
# Clear npm cache and reinstall
docker exec web-container rm -rf node_modules package-lock.json
docker exec web-container npm install
```

#### Prevention

- Pin Node version in `.nvmrc` or Dockerfile
- Run `npm run check` in CI

### Static Assets Not Loading

#### Problem

CSS, JavaScript, or image assets return 404 errors.

#### Diagnostic Steps

```bash
# Verify build output
docker exec web-container ls -la /app/dist/

# Check Nginx serving
curl -I https://kubelab.live/assets/main.css

# Verify cache headers
curl -I https://kubelab.live | grep -i cache
```

#### Solution

- Verify the build output directory matches the Nginx root
- Check asset path prefixes in Astro configuration
- Clear Nginx cache if stale assets are served

### HTMX Not Working

#### Problem

HTMX dynamic interactions fail or produce errors.

#### Diagnostic Steps

```bash
# Check browser console for JavaScript errors
# Verify htmx is loaded
curl https://kubelab.live | grep htmx

# Test API endpoints HTMX calls
curl -X POST https://api.kubelab.live/endpoint \
  -H "HX-Request: true"
```

#### Solution

- Verify HTMX library is included in the page
- Check API responses include correct `HX-` headers
- Verify CORS configuration allows HTMX requests
