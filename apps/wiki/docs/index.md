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
├── 1. apps/                   # Applications
│   ├── 1.1 api/               # Go REST API
│   ├── 1.2 blog/              # Jekyll blog
│   ├── 1.3 web/               # Astro frontend
│   └── 1.4 wiki/              # MkDocs documentation
├── 2. infra/                  # Infrastructure configuration
│   ├── 2.1 traefik/           # Reverse proxy
│   ├── 2.2 nginx/             # Web server configs
│   ├── 2.3 ansible/           # Deployment automation
│   └── 2.4 monitoring/        # Grafana, Prometheus, etc.
├── 3. scripts/                # Automation scripts
├── 4. guides/                 # Documentation guides
└── Makefile                   # Command automation
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

## Navigation

Explore the different sections of this documentation:

<div class="cards">
  <a href="apps/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h3>
      <span style="background: linear-gradient(135deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; margin-right: 0.75rem;">1</span>
      Applications
    </h3>
    <p>Documentation for each app - API, web, blog, and wiki with setup guides and technical details.</p>
    <div style="margin-top: 1rem; color: var(--md-accent-fg-color); font-weight: 600;">
      Explore Apps →
    </div>
  </a>
  
  <a href="infra/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h3>
      <span style="background: linear-gradient(135deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; margin-right: 0.75rem;">2</span>
      Infrastructure
    </h3>
    <p>Server setup, networking, proxies, DNS, deployments and infrastructure management.</p>
    <div style="margin-top: 1rem; color: var(--md-accent-fg-color); font-weight: 600;">
      View Infrastructure →
    </div>
  </a>
  
  <a href="scripts/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h3>
      <span style="background: linear-gradient(135deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; margin-right: 0.75rem;">3</span>
      Scripts
    </h3>
    <p>Automation scripts, deployment utilities and development tools used throughout the project.</p>
    <div style="margin-top: 1rem; color: var(--md-accent-fg-color); font-weight: 600;">
      View Scripts →
    </div>
  </a>
  
  <a href="guides/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h3>
      <span style="background: linear-gradient(135deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.8rem; font-weight: 700; margin-right: 0.75rem;">4</span>
      Guides
    </h3>
    <p>Step-by-step guides, troubleshooting, architecture documentation and detailed procedures.</p>
    <div style="margin-top: 1rem; color: var(--md-accent-fg-color); font-weight: 600;">
      Access Guides →
    </div>
  </a>
</div>

## Quick access by need

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; margin: 2rem 0;">
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">Urgent Problem</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">System down, critical error, service unavailable</p>
    <a href="guides/TROUBLESHOOTING/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">Troubleshooting →</a>
  </div>
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">Quick Command</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">Need to run something specific right now</p>
    <a href="guides/HOW-TO/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">Commands Guide →</a>
  </div>
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">Deploy</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">Setup environment, deploy, release</p>
    <a href="guides/DEPLOYMENT/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">Deployment Guide →</a>
  </div>
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">Architecture</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">Understand decisions, system design</p>
    <a href="guides/ARCHITECTURE-AND-DECISIONS/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">View Architecture →</a>
  </div>
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">CI/CD</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">Pipelines, automation, workflows</p>
    <a href="guides/CI-CD/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">Configure CI/CD →</a>
  </div>
  
  <div style="background: linear-gradient(135deg, rgba(0, 128, 153, 0.1), rgba(0, 128, 153, 0.05)); border-left: 4px solid var(--md-accent-fg-color); padding: 1rem; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: var(--color-teal-700); font-size: 1rem;">Contribute</h4>
    <p style="margin: 0 0 0.75rem 0; font-size: 0.9rem; color: var(--md-default-fg-color--light);">Development standards and contribution</p>
    <a href="guides/CONTRIBUTING/" style="color: var(--color-teal-700); font-weight: 600; text-decoration: none; font-size: 0.9rem;">Guidelines →</a>
  </div>

</div>

## System status

| Component | Status | Documentation |
|-----------|--------|---------------|
| **Applications** | Active | [Apps](apps/) |
| **Infrastructure** | Stable | [Infra](infra/) |
| **Scripts** | Updated | [Scripts](scripts/) |
| **Documentation** | Synchronized | [Guides](guides/) |

---

Built with Docker, automated with GitHub Actions, deployed with Ansible.