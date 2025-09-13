# mlorente.dev

Personal ecosystem monorepo for [mlorente.dev](https://mlorente.dev) - portfolio, blog, API and infrastructure.

This is my personal project where I keep everything needed to run mlorente.dev. It's designed as a monorepo that includes everything from the frontend to the infrastructure. I've organized it this way to have everything under control and be able to deploy easily.

## What's included

- **Web** (Astro) - Personal portfolio website
- **Blog** (Jekyll) - Technical writing and articles
- **API** (Go) - Backend services and REST API
- **Wiki** (MkDocs) - This documentation you're reading
- **Infrastructure** - Docker, Traefik, Nginx, monitoring
- **Automation** - n8n workflows, GitHub Actions, Ansible

## Quick start

```bash
# Clone and setup
git clone <repo-url>
make install-precommit-hooks

# Start everything locally
make up

# View logs
make logs

# Stop everything
make down
```

## Project structure

```
mlorente.dev/
├── apps/                   # Applications
│   ├── api/               # Go REST API
│   ├── blog/              # Jekyll blog
│   ├── web/               # Astro frontend
│   └── wiki/              # MkDocs documentation
├── infra/                 # Infrastructure configuration
│   ├── traefik/           # Reverse proxy
│   ├── nginx/             # Web server configs
│   ├── ansible/           # Deployment automation
│   └── monitoring/        # Grafana, Prometheus, etc.
├── scripts/               # Automation scripts
├── docs/                  # Documentation guides
└── Makefile              # Command automation
```

## Requirements

- Docker & Docker Compose
- Make
- Node.js 20+ (for web apps)
- Go 1.21+ (for API)
- Ruby 3.3+ (for blog)
- Python 3.8+ (for deployment)

## Available commands

The Makefile provides all the commands you need to work with this project. Here are the most important ones:

### Setup and installation

```bash
make check                     # Check prerequisites
make install-precommit-hooks   # Set up development tools
make install-node             # Install Node.js dependencies for web
make install-ruby             # Install Ruby dependencies for blog
make install-ansible          # Install deployment tools
```

### Development

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

Each service will be available at its local domain (add these to your `/etc/hosts`):
- API: http://api.mlorentedev.test
- Web: http://mlorentedev.test  
- Blog: http://blog.mlorentedev.test
- Wiki: http://wiki.mlorentedev.test
- Traefik: http://traefik.mlorentedev.test
- Grafana: http://grafana.mlorentedev.test

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

### Deployment

```bash
make setup ENV=production     # Initial server setup
make deploy ENV=staging       # Deploy to staging
make deploy ENV=production    # Deploy to production
make status ENV=production    # Check deployment status
```

### Utilities

```bash
make generate-config          # Generate all configuration files
make wiki-sync               # Generate documentation wiki
make validate-yaml           # Validate YAML files
make setup-secrets           # Configure GitHub secrets
make list-secrets            # List GitHub secrets
```

## How deployment works

Images are built automatically when you push changes to the repository via GitHub Actions. However, deployment is manual - you run `make deploy ENV=production` when you're ready. This gives you control over when changes go live.

The deployment process:
1. Code changes trigger GitHub Actions
2. Actions build and push Docker images
3. You manually deploy with `make deploy ENV=production`
4. Ansible handles the deployment to servers

## Local development workflow

1. **First time setup:**
   ```bash
   git clone <repo-url>
   make install-precommit-hooks
   make up
   ```

2. **Daily development:**
   ```bash
   # Start services you need
   make up-traefik up-api up-web
   
   # Make your changes
   # Test locally
   
   # Stop when done
   make down
   ```

3. **Before pushing changes:**
   ```bash
   make validate-yaml           # Check YAML files
   git add . && git commit      # Pre-commit hooks will run
   git push                     # Triggers CI/CD
   ```

## Environment files

Each service uses an `.env` file for configuration. Examples are provided:
- Copy `.env.example` to `.env` for each service
- Set `ENVIRONMENT=local` for development
- Update values as needed for your setup

## Monitoring and debugging

View logs:
```bash
make logs                     # All services
make logs APP=api            # Specific service
```

Check service health:
```bash
make status                  # Local status
make status ENV=production   # Production status
```

Access monitoring:
- Traefik dashboard: http://traefik.mlorentedev.test/dashboard
- Grafana: http://grafana.mlorentedev.test
- Container management: http://portainer.mlorentedev.test

## Documentation

This wiki contains detailed documentation for all aspects of the project:

1. **[Applications](apps/)** - Documentation for each app (API, web, blog, wiki)
2. **[Infrastructure](infra/)** - Server setup, networking, monitoring
3. **[Scripts](scripts/)** - Automation scripts and utilities  
4. **[Guides](guides/)** - Step-by-step guides and troubleshooting

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Set up development: `make install-precommit-hooks && make up`
4. Make changes and test locally
5. Submit a pull request

See the [Contributing Guide](guides/CONTRIBUTING/) for detailed guidelines.

## License

MIT - see [LICENSE](LICENSE) file for details.

---

Built with Docker, automated with GitHub Actions, deployed with Ansible.