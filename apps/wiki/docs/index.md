 cubelab.cloud

Personal ecosystem monorepo for [cubelab.cloud](https://cubelab.cloud) - portfolio, blog, API and infrastructure.

This is my personal project where I keep everything needed to run cubelab.cloud. It's designed as a monorepo that includes everything from the frontend to the infrastructure. I've organized it this way to have everything under control and be able to deploy easily.

 What's included

- Web (Astro) - Personal portfolio website
- Blog (Jekyll) - Technical writing and articles
- API (Go) - Backend services and REST API
- Wiki (MkDocs) - This documentation you're reading
- Infrastructure - Docker, Traefik, Nginx, monitoring
- Automation - nn workflows, GitHub Actions, Ansible

 Quick start

```bash
 Clone and setup
git clone <repo-url>
make install-precommit-hooks

 Start everything locally
make up

 View logs
make logs

 Stop everything
make down
```

 Project structure

```
cubelab.cloud/
├── . apps/                    Applications
│   ├── . api/                Go REST API
│   ├── . blog/               Jekyll blog
│   ├── . web/                Astro frontend
│   └── . wiki/               MkDocs documentation
├── . infra/                   Infrastructure configuration
│   ├── . traefik/            Reverse proxy
│   ├── . nginx/              Web server configs
│   ├── . ansible/            Deployment automation
│   └── . monitoring/         Grafana, Prometheus, etc.
├── . scripts/                 Automation scripts
├── . guides/                  Documentation guides
└── Makefile                    Command automation
```

 Requirements

- Docker & Docker Compose
- Make
- Node.js + (for web apps)
- Go .+ (for API)
- Ruby .+ (for blog)
- Python .+ (for deployment)

 Available commands

The Makefile provides all the commands you need to work with this project. Here are the most important ones:

 Setup and installation

```bash
make check                      Check prerequisites
make install-precommit-hooks    Set up development tools
make install-node              Install Node.js dependencies for web
make install-ruby              Install Ruby dependencies for blog
make install-ansible           Install deployment tools
```

 Development

Start individual services:
```bash
make up-traefik                Start reverse proxy (required first)
make up-api                    Start Go API
make up-web                    Start Astro frontend
make up-blog                   Start Jekyll blog
make up-wiki                   Start documentation wiki
make up-nn                    Start automation workflows
make up-grafana                Start monitoring dashboard
```

Start everything at once:
```bash
make up                        Start all services
make down                      Stop all services
```

Each service will be available at its local domain (add these to your `/etc/hosts`):
- API: http://api.mlorentedev.test
- Web: http://mlorentedev.test  
- Blog: http://blog.mlorentedev.test
- Wiki: http://wiki.mlorentedev.test
- Traefik: http://traefik.mlorentedev.test
- Grafana: http://grafana.mlorentedev.test

 Building and publishing

Build Docker images:
```bash
make build-image APP=api       Build specific app image
make build-all-images          Build all application images
```

Publish to registry:
```bash
make push-app APP=api          Push specific app
make push-all                  Push all apps
make push-app-tag APP=api TAG=v..     Push with specific tag
```

 Deployment

```bash
make setup ENV=production      Initial server setup
make deploy ENV=staging        Deploy to staging
make deploy ENV=production     Deploy to production
make status ENV=production     Check deployment status
```

 Utilities

```bash
make generate-config           Generate all configuration files
make wiki-sync                Generate documentation wiki
make validate-yaml            Validate YAML files
make setup-secrets            Configure GitHub secrets
make list-secrets             List GitHub secrets
```

 How deployment works

Images are built automatically when you push changes to the repository via GitHub Actions. However, deployment is manual - you run `make deploy ENV=production` when you're ready. This gives you control over when changes go live.

The deployment process:
. Code changes trigger GitHub Actions
. Actions build and push Docker images
. You manually deploy with `make deploy ENV=production`
. Ansible handles the deployment to servers

 Local development workflow

. First time setup:
   ```bash
   git clone <repo-url>
   make install-precommit-hooks
   make up
   ```

. Daily development:
   ```bash
    Start services you need
   make up-traefik up-api up-web
   
    Make your changes
    Test locally
   
    Stop when done
   make down
   ```

. Before pushing changes:
   ```bash
   make validate-yaml            Check YAML files
   git add . && git commit       Pre-commit hooks will run
   git push                      Triggers CI/CD
   ```

 Environment files

Each service uses an `.env` file for configuration. Examples are provided:
- Copy `.env.example` to `.env` for each service
- Set `ENVIRONMENT=local` for development
- Update values as needed for your setup

 Monitoring and debugging

View logs:
```bash
make logs                      All services
make logs APP=api             Specific service
```

Check service health:
```bash
make status                   Local status
make status ENV=production    Production status
```

Access monitoring:
- Traefik dashboard: http://traefik.mlorentedev.test/dashboard
- Grafana: http://grafana.mlorentedev.test
- Container management: http://portainer.mlorentedev.test

 Navigation

Explore the different sections of this documentation:

<div class="cards">
  <a href="apps/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h>
      <span style="background: linear-gradient(deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: .rem .rem; border-radius: px; font-size: .rem; font-weight: ; margin-right: .rem;"></span>
      Applications
    </h>
    <p>Documentation for each app - API, web, blog, and wiki with setup guides and technical details.</p>
    <div style="margin-top: rem; color: var(--md-accent-fg-color); font-weight: ;">
      Explore Apps →
    </div>
  </a>
  
  <a href="infra/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h>
      <span style="background: linear-gradient(deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: .rem .rem; border-radius: px; font-size: .rem; font-weight: ; margin-right: .rem;"></span>
      Infrastructure
    </h>
    <p>Server setup, networking, proxies, DNS, deployments and infrastructure management.</p>
    <div style="margin-top: rem; color: var(--md-accent-fg-color); font-weight: ;">
      View Infrastructure →
    </div>
  </a>
  
  <a href="scripts/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h>
      <span style="background: linear-gradient(deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: .rem .rem; border-radius: px; font-size: .rem; font-weight: ; margin-right: .rem;"></span>
      Scripts
    </h>
    <p>Automation scripts, deployment utilities and development tools used throughout the project.</p>
    <div style="margin-top: rem; color: var(--md-accent-fg-color); font-weight: ;">
      View Scripts →
    </div>
  </a>
  
  <a href="guides/" class="card clickable-card" style="text-decoration: none; color: inherit;">
    <h>
      <span style="background: linear-gradient(deg, var(--md-accent-fg-color), var(--md-primary-fg-color)); color: white; padding: .rem .rem; border-radius: px; font-size: .rem; font-weight: ; margin-right: .rem;"></span>
      Guides
    </h>
    <p>Step-by-step guides, troubleshooting, architecture documentation and detailed procedures.</p>
    <div style="margin-top: rem; color: var(--md-accent-fg-color); font-weight: ;">
      Access Guides →
    </div>
  </a>
</div>

 Quick access by need

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(px, fr)); gap: rem; margin: rem ;">
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">Urgent Problem</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">System down, critical error, service unavailable</p>
    <a href="guides/TROUBLESHOOTING/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">Troubleshooting →</a>
  </div>
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">Quick Command</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">Need to run something specific right now</p>
    <a href="guides/HOW-TO/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">Commands Guide →</a>
  </div>
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">Deploy</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">Setup environment, deploy, release</p>
    <a href="guides/DEPLOYMENT/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">Deployment Guide →</a>
  </div>
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">Architecture</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">Understand decisions, system design</p>
    <a href="guides/ARCHITECTURE-AND-DECISIONS/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">View Architecture →</a>
  </div>
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">CI/CD</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">Pipelines, automation, workflows</p>
    <a href="guides/CI-CD/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">Configure CI/CD →</a>
  </div>
  
  <div style="background: linear-gradient(deg, rgba(, , , .), rgba(, , , .)); border-left: px solid var(--md-accent-fg-color); padding: rem; border-radius: px;">
    <h style="margin:   .rem ; color: var(--color-teal-); font-size: rem;">Contribute</h>
    <p style="margin:   .rem ; font-size: .rem; color: var(--md-default-fg-color--light);">Development standards and contribution</p>
    <a href="guides/CONTRIBUTING/" style="color: var(--color-teal-); font-weight: ; text-decoration: none; font-size: .rem;">Guidelines →</a>
  </div>

</div>

 System status

| Component | Status | Documentation |
|-----------|--------|---------------|
| Applications | Active | [Apps](apps/) |
| Infrastructure | Stable | [Infra](infra/) |
| Scripts | Updated | [Scripts](scripts/) |
| Documentation | Synchronized | [Guides](guides/) |

---

Built with Docker, automated with GitHub Actions, deployed with Ansible.
