# My Personal Ecosystem - mlorente.dev

<div align="center">

![Status](https://img.shields.io/badge/Status-Production-008099?style=flat&logo=rocket&logoColor=white)
![License](https://img.shields.io/github/license/mlorentedev/mlorente.dev?style=flat&color=008099)
![CI/CD](https://img.shields.io/github/actions/workflow/status/mlorentedev/mlorente.dev/ci-01-dispatch.yml?style=flat&label=Build&color=008099)

![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)
![Ansible](https://img.shields.io/badge/Ansible-EE0000?style=flat&logo=ansible&logoColor=white)
![Traefik](https://img.shields.io/badge/Traefik-24A1C1?style=flat&logo=traefik&logoColor=white)
![Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat&logo=github-actions&logoColor=white)

</div>

Hello! This is my personal project where I have everything I need to keep [mlorente.dev](https://mlorente.dev) running. It's a monorepo that includes everything from the front-end to the infrastructure, including the blog and API. I've organized it this way to have everything under control and be able to deploy easily.

**What does it include?**

* **My personal website** built with **Astro** (`apps/web`) - here you have my portfolio and all info about me
* **My blog** in **Jekyll** (`apps/blog`) - where I write about technology and development  
* **The API** in **Go** (`apps/api`) - handles newsletter subscriptions and other things
* **n8n** for automating repetitive tasks without code
* **Complete monitoring** with **Prometheus**, **Grafana** and **Vector** - because I like to know what's happening
* **Portainer** for visual container management
* **Traefik** and **Nginx** as reverse proxies
* **Ansible** for automatic deployment
* **GitHub Actions** for CI/CD - images build themselves
* **A Makefile** that simplifies my life with commands like `make up`, `make deploy`, etc.

> **Important note:** Images are built and published automatically when I push, but **I prefer to deploy manually** by running `make deploy` on the server. It gives me more control.

---

## Table of contents

1. [How everything is organized](#how-everything-is-organized)
2. [What you need](#what-you-need)
3. [Quick start](#quick-start)
4. [Local development](#local-development)
5. [CI with GitHub Actions](#ci-with-github-actions)
6. [Deployments](#deployments)
7. [Useful Makefile commands](#useful-makefile-commands)
8. [Frequently asked questions](#frequently-asked-questions)
9. [License](#license)

---

## How everything is organized

```text
.
├── apps/                  # The applications I use
│   ├── api/               # Go API (containerized)
│   ├── blog/              # Static Jekyll blog
│   ├── web/               # My main website in Astro
│   ├── n8n/               # Automations with n8n
│   ├── monitoring/        # Vector, Prometheus, Grafana
│   └── portainer/         # Visual Docker management
├── infra/                 # The infrastructure
│   ├── ansible/           # Deployment playbooks
│   ├── traefik/           # Proxy configuration
│   └── nginx/             # Error pages, fallback
├── scripts/               # Useful scripts for generating configs
├── .github/workflows/     # CI (builds and publishes) — doesn't deploy
├── Makefile               # My swiss army knife (dev / build / deploy)
├── .env.example           # Example variables
└── docs/                  # Extra documentation
```

---

## What you need

| Tool                       | Version           | What I use it for               |
| -------------------------- | ----------------- | ------------------------------- |
| **Docker Engine**          | 24 or higher      | Containers in local and prod    |
| **Docker Compose v2**      | 2.20 or higher    | Orchestrate services            |
| **Make**                   | 4.2 or higher     | Simplify commands               |
| **Git**                    | Whatever you have | Version control                 |
| **Node 20** and **npm 10** | (if you touch web)| For the frontend                |
| **Ruby 3.2** and **Bundler**| (if you touch blog)| For Jekyll                     |
| **Go 21**                  | (if you touch API)| For the backend                 |
| **Ansible**                | 9 or higher       | Automatic deployments          |

> **Optional:** **gh CLI** for managing GitHub secrets and **jq** for processing JSON.

---

## Quick start

```bash
# 1. Clone the repository
$ git clone git@github.com:mlorente/mlorente.dev.git && cd mlorente.dev

# 2. Configure your variables (copy and edit)
$ cp .env.example .env && $EDITOR .env

# 3. Install what you need
$ make env-setup  # installs the necessary tools

# 4. Let's get it working!
$ make up         # Brings up Traefik + all apps

# 5. Now you can access:
#   http://site.mlorentedev.test (main website)
#   http://blog.mlorentedev.test (blog)
#   http://api.mlorentedev.test/api (API)
#   http://traefik.mlorentedev.test:8080 (Traefik dashboard)
```

**Some tips:**

1. Add `*.mlorentedev.test` to your `/etc/hosts` if you don't have local DNS configured.
2. Each app has its `.env.example` - copy it if you need specific variables.
3. Only want to bring up one thing? Use `make up-web`, `make up-blog`, etc.

---

## Local development

```mermaid
graph TD;
  A[make up-traefik] --> B1[make up-blog];
  A --> B2[make up-web];
  A --> B3[make up-api];
  subgraph Browser
    C1(site.mlorentedev.test) --> A;
  end
```

My usual workflow:

1. **Traefik** comes up first and manages all local domains for me.
2. Each service rebuilds automatically when I change code (`docker compose ...dev.yml`).
3. Hot-reload enabled: Astro on port **4321**, Jekyll on **4000**, Go with **air** for automatic reload.
4. To see logs: `make logs`.
5. To stop everything: `make down` (or `docker compose down -v` in each folder).

---

## CI with GitHub Actions

| Phase            | Workflow                                   | What it does                                                                                                                                                  |
| ---------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dispatcher**   | `ci-01-dispatch.yml`                       | Detects which **apps** have changed and launches builds in parallel                                                                                          |
| **Build + Push** | `ci-02-pipeline.yml` → `ci-03-publish.yml` | Linters + tests → `docker buildx` **multi-architecture** → push to Docker Hub with tags:<br> `latest`, semver (`vX.Y.Z`), branch (`develop`, `feature/…`) |
| **Release**      | `ci-04-release.yml`                        | Manual official version (`gh release`) → re-tags images → generates bundle `global-release-vX.Y.Z.zip`                                                      |

**The result:** I have all images ready in the registry, but *they don't deploy automatically*.

---

## Deployments

> **Recommendation:** use a dedicated user (like `mlorente-deployer`) with *passwordless sudo* access and **Docker** already installed on the server.

1. **Prepare the server** (only the first time)

   ```bash
   make setup ENV=production SSH_HOST=mlorente-deployer@my.server.com
   ```

   This installs packages, creates Docker network, copies base configurations...

2. **Deploy or update**

   ```bash
   make deploy ENV=production
   ```

   Behind the scenes it runs: `ansible-playbook infra/ansible/playbooks/deploy.yml -e env=production`.

3. **Verify everything is working**

   ```bash
   make status ENV=production   # docker ps on remote
   make logs   ENV=production   # see logs in real time
   ```

4. **Rollback**: everything is versioned with *tags* → you just need to change variables and run `make deploy` again.

---

## Useful Makefile commands

| Category     | Command                              | What it does                      |
| ------------ | ------------------------------------ | --------------------------------- |
| Setup        | `make check`                         | Checks you have everything        |
|              | `make env-setup`                     | Installs Node, Ruby, Go          |
|              | `make create-network`                | Creates `mlorente_net` network    |
| Development  | `make up`                            | Brings up Traefik + all apps      |
|              | `make up-web` / `up-api` / `up-blog` | Just one service                  |
|              | `make down`                          | Stops everything                  |
| Build / Push | `make push-app APP=web`              | Builds + multi-arch push          |
|              | `make push-all`                      | All apps at once                  |
| Deploy       | `make setup ENV=staging`             | Prepares remote server            |
|              | `make deploy ENV=staging`            | Deploys images                    |
| Utilities    | `make generate-config`               | Generates configurations          |
|              | `make setup-secrets`                 | Syncs `.env` → GitHub             |

> Run `make help` to see the complete list with nice colors.

---

## 📚 Additional documentation

If you want to dive deeper, I have all this documentation:

- **[⚡ How-To - Quick Reference](docs/HOW-TO.md)** - **Main entry point** - Commands, common tasks and quick navigation
- **[🏗️ ADRs - Architecture Decisions](docs/ADR.md)** - 10 Architecture Decision Records where I explain the "why" of each decision
- **[🏷️ Versioning Strategy](docs/VERSIONING.md)** - How Docker images and releases per branch work  
- **[🚀 Advanced Deployment](docs/DEPLOYMENT.md)** - Advanced server configuration and deployments
- **[🔧 Troubleshooting](docs/TROUBLESHOOTING.md)** - Solutions to common problems and debugging  
- **[⚙️ CI/CD Internals](docs/CI-CD.md)** - Internal workings of the workflows
- **[👥 Contribution Guide](docs/CONTRIBUTING.md)** - Code conventions and development flow

---

## Frequently asked questions

**Do I need Ansible for local development?** 
Not at all. Only for remote deployments.

**Could deployment be automated too?** 
Sure, it would be enough to add a job that, after `ci-02-pipeline`, runs `make deploy` with `ansible-playbook` on the runner.

**How do I manage certificates in staging?** 
Use `make copy-certificates ENV=staging` and add them to your local trust store.

**Can I change the local URL?** 
Yes, change `DOMAIN_LOCAL` in `.env` and update your `/etc/hosts`.

---

## License

[MIT](LICENSE)

---

> *"Works on my machine"* no me vale. Con este Makefile y Ansible, los despliegues son **reproducibles** y **predecibles** en cualquier sitio.