---
id: "kubelab-troubleshooting-application-debugging"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab]
created: "2026-02-08"
owner: manu
---

# Application Debugging

Troubleshooting KubeLab's custom applications: API (Go), Web (Astro), Blog (Jekyll), and Wiki (MkDocs).

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

## Blog (Jekyll)

### Build Failures

#### Problem

Jekyll site fails to build.

#### Diagnostic Steps

```bash
# Check Ruby version
docker exec blog-container ruby --version

# Verify Gemfile.lock
docker exec blog-container bundle check

# Local build
cd apps/blog/jekyll-site
bundle exec jekyll build --verbose
```

#### Solution

```bash
# Rebuild dependencies
docker exec blog-container bundle install
docker exec blog-container bundle update
```

### Posts Not Appearing

#### Problem

New blog posts are not visible on the site.

#### Diagnostic Steps

```bash
# Check post frontmatter
head -20 apps/blog/jekyll-site/_posts/2024-01-01-post.md

# Verify date format (YYYY-MM-DD)
ls -la apps/blog/jekyll-site/_posts/

# Check build output
docker exec blog-container ls -la /app/_site/
```

#### Solution

```bash
# Rebuild site
toolkit apps restart blog
```

#### Prevention

- Validate frontmatter in CI
- Use consistent date format (YYYY-MM-DD) in post filenames
- Future-dated posts are not published by default in Jekyll

### Theme/CSS Issues

#### Problem

Blog theme or styling is broken.

#### Diagnostic Steps

```bash
# Verify theme configuration
docker exec blog-container cat /app/_config.yml | grep theme

# Check CSS compilation
docker exec blog-container bundle exec jekyll build --trace

# Clear Jekyll cache
docker exec blog-container rm -rf /app/.jekyll-cache
```

#### Solution

- Verify theme gem is installed and version is correct
- Clear Jekyll cache and rebuild
- Check for SASS compilation errors in build output

## Wiki (MkDocs)

### Build Failures

#### Problem

MkDocs documentation site fails to build.

#### Diagnostic Steps

```bash
# Check Python version
docker exec wiki-container python --version

# Verify dependencies
docker exec wiki-container pip list | grep mkdocs

# Build locally
cd apps/wiki
mkdocs build --strict

# Check for broken links
mkdocs build --strict 2>&1 | grep -i "warning\|error"
```

#### Solution

- Fix any broken internal links reported by `--strict` mode
- Update MkDocs and plugin versions if incompatibilities exist

### Navigation Not Working

#### Problem

MkDocs navigation sidebar is broken or incomplete.

#### Diagnostic Steps

```bash
# Verify mkdocs.yml structure
cat apps/wiki/mkdocs.yml | grep -A 20 nav:

# Check for duplicate page entries
grep -r "\.md" apps/wiki/docs/ | sort | uniq -d
```

#### Solution

```bash
# Rebuild navigation
toolkit apps restart wiki
```

#### Prevention

- Validate `mkdocs.yml` in CI
- Use consistent page naming conventions

### Search Not Working

#### Problem

MkDocs search returns no results or is unavailable.

#### Diagnostic Steps

```bash
# Verify search plugin
docker exec wiki-container cat /app/mkdocs.yml | grep search

# Check search index
docker exec wiki-container ls -la /app/site/search/

# Rebuild with verbose output
docker exec wiki-container mkdocs build --verbose
```

#### Solution

- Ensure the `search` plugin is enabled in `mkdocs.yml`
- Rebuild the site to regenerate the search index
- Check that JavaScript is not blocked by CSP headers
