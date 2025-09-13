# 4.10 Makefile - Command Reference

The Makefile is the heart of this project's automation. It provides a unified interface for all common operations, from development to deployment. Every command you need to work with mlorente.dev is available through make.

## What it does

The Makefile acts as a central command hub that abstracts away the complexity of managing a multi-application monorepo. Instead of remembering different commands for each service, you just use make commands that handle everything consistently.

## Core commands

### Setup and installation

```bash
make check                     # Check prerequisites
make install-precommit-hooks   # Set up development tools
make install-node             # Install Node.js dependencies for web
make install-ruby             # Install Ruby dependencies for blog
make install-ansible          # Install deployment tools
```

### Development workflow

Start individual services:
```bash
make up-traefik               # Start reverse proxy (required first)
make up-api                   # Start Go API
make up-web                   # Start Astro frontend
make up-blog                  # Start Jekyll blog
make up-wiki                  # Start documentation wiki
make up-n8n                   # Start automation workflows
make up-grafana               # Start monitoring dashboard
```

Start everything at once:
```bash
make up                       # Start all services
make down                     # Stop all services
```

### Building and publishing

Build Docker images:
```bash
make build-image APP=api      # Build specific app image
make build-all-images         # Build all application images
```

Publish to registry:
```bash
make push-app APP=api         # Push specific app
make push-all                 # Push all apps
make push-app-tag APP=api TAG=v1.0.0    # Push with specific tag
```

### Deployment operations

```bash
make setup ENV=production     # Initial server setup
make deploy ENV=staging       # Deploy to staging
make deploy ENV=production    # Deploy to production
make status ENV=production    # Check deployment status
```

### Maintenance and utilities

```bash
make generate-config          # Generate all configuration files
make wiki-sync               # Generate documentation wiki
make validate-yaml           # Validate YAML files
make setup-secrets           # Configure GitHub secrets
make list-secrets            # List GitHub secrets
```

### Monitoring and debugging

```bash
make logs                    # View logs from all services
make logs APP=api           # View logs from specific service
make health                 # Check health of all services
make ps                     # Show running containers
```

## Local development URLs

When you run services locally with make commands, they're available at:

- **API**: http://api.mlorentedev.test
- **Web**: http://mlorentedev.test  
- **Blog**: http://blog.mlorentedev.test
- **Wiki**: http://wiki.mlorentedev.test
- **Traefik Dashboard**: http://traefik.mlorentedev.test
- **Grafana**: http://grafana.mlorentedev.test

Add these entries to your `/etc/hosts` file:
```
127.0.0.1 mlorentedev.test
127.0.0.1 api.mlorentedev.test
127.0.0.1 blog.mlorentedev.test
127.0.0.1 wiki.mlorentedev.test
127.0.0.1 traefik.mlorentedev.test
127.0.0.1 grafana.mlorentedev.test
```

## Environment management

The Makefile handles different environments automatically:

- **Local development**: Uses `.env` files and `docker-compose.yml`
- **Staging**: Uses staging-specific configurations
- **Production**: Uses production configurations with proper secrets

## Prerequisites checking

Before running any commands, the Makefile checks that you have:

- Docker and Docker Compose installed
- Required permissions for Docker
- Network connectivity
- Proper directory structure

## Error handling

All make commands include proper error handling:

- **Dependency checks**: Ensures prerequisites are met
- **Clean failures**: Stops gracefully on errors
- **Helpful messages**: Clear error descriptions
- **Recovery suggestions**: What to do when things fail

## Custom variables

You can customize behavior with environment variables:

```bash
# Use different Docker registry
export DOCKER_REGISTRY=my-registry.com
make push-all

# Use different environment
export ENVIRONMENT=staging
make deploy

# Enable debug mode
export DEBUG=1
make up
```

## Advanced usage

### Parallel operations

```bash
# Start multiple services in parallel
make up-api up-web up-blog

# Build multiple images simultaneously
make build-image APP=api & make build-image APP=web & wait
```

### Conditional execution

```bash
# Only deploy if tests pass
make test && make deploy ENV=production

# Build and push in one command
make build-all-images && make push-all
```

### Development shortcuts

```bash
# Quick restart of a service
make down APP=api && make up-api

# Full rebuild and restart
make build-image APP=api && make up-api
```

## Integration with CI/CD

The Makefile commands are used throughout the CI/CD pipeline:

- **GitHub Actions** use make commands for consistency
- **Local development** mirrors CI/CD exactly
- **Production deployment** uses the same commands
- **Testing** runs through make targets

## Troubleshooting

### Common make issues

**Command not found:**
```bash
# Ensure you're in the project root
pwd
ls Makefile
```

**Permission denied:**
```bash
# Check Docker permissions
make check
```

**Service won't start:**
```bash
# Check logs
make logs APP=service-name

# Restart clean
make down && make up
```

### Debug mode

Enable verbose output for debugging:
```bash
export DEBUG=1
make up
```

## Extending the Makefile

To add new commands, follow these patterns:

```makefile
# New service command
up-myservice:
	@echo "Starting my service..."
	docker-compose -f docker-compose.yml up -d myservice

# New utility command  
my-utility:
	@echo "Running my utility..."
	./scripts/my-script.sh
```

## Best practices

1. **Always use make commands** - Don't run docker-compose directly
2. **Check prerequisites first** - Run `make check` on new systems
3. **Use specific targets** - `make up-api` instead of `make up` when developing
4. **Check logs on failures** - `make logs APP=service` for debugging
5. **Keep environment clean** - `make down` when switching contexts

The Makefile is designed to make your life easier. When in doubt, run `make help` to see all available commands with descriptions.