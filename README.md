# mlorente.dev

This is my minimal website [mlorente.dev](https://mlorente.dev) with modern architecture based in containers.

## Architecture

This project  uses a microservice architecture with the following technologies:

- **Frontend**: Astro with HTMX and Tailwind CSS
- **Backend**: API RESTful with Go and Gin
- **Deployment**: Docker containers in Hetzner Cloud

Inside of this project, you'll see the following folders and files:

```text
|── .github/
|   |── workflows/
|── .vscode/
├── backend
│   ├── cmd
│   │   └── server
│   ├── internal
│   │   ├── api
│   │   ├── constants
│   │   ├── models
│   │   └── services
│   └── pkg
│       ├── config
│       └── logger
├── docker
│   ├── backend
│   ├── frontend
│   └── nginx
├── frontend
│   ├── public
│   │   ├── cv
│   │   ├── fonts
│   │   ├── images
│   │   │   ├── homelab
│   │   │   └── me
│   │   └── pdf
│   └── src
│       ├── components
│       │   ├── common
│       │   ├── features
│       │   │   ├── booking
│       │   │   ├── homelab
│       │   │   ├── recent
│       │   │   └── subscription
│       │   └── sections
│       ├── content
│       │   ├── projects
│       │   └── resources
│       ├── data
│       ├── layouts
│       ├── pages
│       │   ├── api
│       │   ├── projects
│       │   └── resources
│       └── styles
|── scripts/
|── .env.dev
|── .gitignore
|── CONTRIBUTING.md
|── docker-compose.dev.yml
|── docker-compose.yml
|── LICENSE
|── README.md
```

## Requirements

- [Node.js](https://nodejs.org) version 18.0.0 or higher
- [npm](https://www.npmjs.com/get-npm) version 6.0.0 or higher
- [Docker](https://www.docker.com/get-started) (optional, for deployment)
- [Docker Compose](https://docs.docker.com/compose/install/) (optional, for deployment)
- [Go](https://golang.org/dl/) version 1.18 or higher (optional, for backend development)

## Environment Setup

### Environment variables

This project has a single `.env` file in the root directory that contains environment variables for both the frontend and backend.

- `.env.dev`: Development environment variables
- `/opt/mlorente/.env`: Production environment variables (generated during deployment)

### Initial Setup

1. Clone the repository:

    ```bash
    git clone
    cd mlorente.dev
    ```

2. To configure the development environment:

    ```bash
    # Prepare development environment
    ./scripts/dev-setup.sh

    # Configure GitHub secrets (for CI/CD)
    ./scripts/setup-github-secrets.sh

    # Configure production server on Hetzner
    ./scripts/setup-server.sh 123.456.789.0 production

    # Configure staging server on Hetzner
    ./scripts/setup-server.sh 123.456.789.1 staging
    ```

### Local development

#### Containerized Development

To run the project in a containerized environment for development, use Docker Compose.

```bash
# Start all services
docker-compose -f docker-compose.dev.yml up

# View logs
docker-compose -f docker-compose.dev.yml logs -f

# View logs for a specific service
docker-compose -f docker-compose.dev.yml logs -f <service_name>

# Stop all services
docker-compose -f docker-compose.dev.yml down
```

With this setup:

- Frontend is accessible at `http://localhost:3000`
- Backend is accessible at `http://localhost:8080`

This mode includes:

- Hot reloading for frontend changes with Astro
- Hot reloading for backend changes with Air
- Mounted volumes for easy development

#### Non-Containerized Development

If you prefer not to use Docker for development, you can run the frontend and backend separately.

1. **Frontend**: Navigate to the `frontend` directory and run:

   ```bash
   npm install
   npm run dev
   ```

2. **Backend**: Navigate to the `backend` directory and run:

   ```bash
   go mod download
   go run cmd/server/main.go
    ```

Need to install Air for hot reloading:

```bash
go install github.com/cosmtrek/air@latest
```

### Production Deployment

#### CI/CD

The project is configured for CI/CD using GitHub Actions. Ensure you have set up the necessary secrets in your GitHub repository.

- Any push to the `master` branch will trigger a deployment to production.
- Any push to the `feature/*` or `hotfix/*` branch will trigger a deployment to staging.

The project is configured for automated deployment through GitHub Actions:

1. Frontend CI: Tests and builds the frontend

    - Triggers: Changes in /frontend or related workflows
    - Process: Lint, tests, build and push Docker image
    - Result: Updated Docker image for the frontend

2. Backend CI: Tests and builds the backend

    - Triggers: Changes in /backend or related workflows
    - Process: Go vet, tests, build and push Docker image
    - Result: Updated Docker image for the backend

3. Deploy: Unified deployment

    - Triggers: Completion of CI or manual from GitHub
    - Process: Updates services on the server
    - Scripts: Uses external scripts for complex deployment logic
    - Environments: Staging (for develop branch) or Production (for master branch)

#### Branch strategy

The project follows this branch strategy:

`master`: Stable code for production deployment  
`develop`: Active development and integration  
`feature/*`: Feature branches for new functionality  
`hotfix/*`: Hotfix branches for urgent fixes  

#### Automated Deployment

This project implements an hybrid approach for deployment. The frontend is deployed using GitHub Actions, while the backend is deployed manually with some scripts.

- `scripts/deploy.sh`: Deploy from CI/CD to production
- `scripts/update-env.sh`: Update environment variables
- `scripts/rollback.sh`: Rollback to previous version in case of issues

#### Manual Deployment

If you need to deploy manually, you can use the following commands in the server:

```bash
# Deployment in staging
./scripts/deploy.sh staging

# Deployment in production
./scripts/deploy.sh production

# Direct deployment in production
cd /opt/mlorente
docker-compose pull
docker-compose up -d
```

## API

Backend expose below endpoints:

- `/api/subscribe`: Subscribe to newsletter
- `/api/unsubscribe`: Unsubscribe from newsletter
- `/api/lead-magnet`: Subscribe to newsletter and send lead magnet
- `/api/resource-email`: Send email with resource

## Troubleshooting

- Server does not respond. Check if the containers are running:

```bash
docker-compose ps
docker-compose restart
```

- Frontend gets errors. View logs:

```bash
docker-compose logs frontend
```

- Backend gets errors. View logs:

```bash
docker-compose logs backend
```

- SSL issues. Ensure your domain is correctly configured and SSL certificates are valid or restart certbot:

```bash
docker-compose restart certbot
```

- Environment variables issues. If you are missing environment variables, check the `.env` file or the GitHub secrets.

```bash
# Update environment variables
./scripts/update-env.sh production
```

- If a deployment fails, you can rollback to the previous version:

```bash
# List available versions
./scripts/rollback.sh production

# Rollback to a specific version
./scripts/rollback.sh production v1.2.3
```

## Advanced operations

The project includes several advanced scripts for operations and maintenance:

### Performance testing

To test the performance of the backend:

```bash
# Basic performance test
./scripts/perf-test.sh production

# Test specific endpoint
./scripts/perf-test.sh production /api/subscribe
```

### Security checks

Verify the security configuration of the server:

```bash
# Check server security
./scripts/security-check.sh production
```

### Log analysis

Analyse application logs:

```bash
# Analyze all logs
./scripts/analyze-logs.sh production

# Analyze specific service logs
./scripts/analyze-logs.sh production nginx
```

## Aditional notes

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name and its language parameter.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

The `src/content/` directory contains "collections" of related Markdown and MDX documents.
The `src/content/config.ts` file adds the `slug` key as a property to the collections. This is the slug that will be used in the header, blogs list page and as canonical and alternate URLs.

Any static assets, like images, can be placed in the `public/` directory.

## Server

This project is designed to be deployed on Hetzner Cloud. You can use the `scripts/setup-server.sh` script to configure your environment.

You need to have a Hetzner account and API token to use this script.

This project is intended to be used with CAX21 or higher instances, and initially these are the steps:

1. Create a new server with Ubuntu 22.04 or higher.
2. Enable IPv4 and IPv6.
3. Add a public network interface.
4. Add a private network interface (optional, but recommended for internal communication).
5. SSH key for access.

    ```bash
    ssh-keygen -t ed25519 -C "mlorentedev@deployment"
    # This will create:
    # - Private key: ~/.ssh/id_ed25519
    # - Public key: ~/.ssh/id_ed25519.pub
    ```

6. Intial server hardening:

    - Disable root login
    - Configure fail2ban to protect SSH
    - Setup automatic security updates
    - Configure UFW firewall

7. Connect to the server and run the setup script.

    ```bash
    ssh root@your_server_ip
    bash <(curl -s https://raw.githubusercontent.com/mlorentedev/mlorente.dev/master/scripts/setup-hetzner.sh)
    ```

8. Follow the instructions to complete the setup.
9. After the setup, you can access your site at `http://your_server_ip`.
10. For production, you need to configure a domain and SSL certificates.
11. For staging, you can use a subdomain or a different domain.
12. For SSL, you can use Let's Encrypt with Certbot.

For SSH access, you can use the private key generated in step 5.

```bash
# Copy public key to server manually
ssh-copy-id -i ~/.ssh/id_ed25519.pub deployer@your_server_ip
```

For further details about scripting and automation, refer to the [scripts/README.md](scripts/README.md) file.

## LICENSE

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

## CONTRIBUTING

If you want to contribute to this project, please read the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## TODO

- [ ] Script to populate secrets in GitHub Actions
- [ ] CI/CD with GitHub Actions
- [ ] Testing
- [ ] Deploy to Hetzner
- [ ] HTTPS and Fail2Ban
- [ ] Homelab section: learning-path, homelabs, etc. similar to Collabnix
- [ ] Slack community integration with the API
- [ ] Most recent RRSS in some section - dynamic with CI/CD
- [ ] Indexed search by tags
- [ ] Copy in all pages
- [ ] Simple and minimalistic design
- [ ] Google Analytics
- [ ] Observability with TIG or PLG stack + alerts // Loki + Netdata
- [ ] Docker secrets or Vault for sensitive data
- [ ] Healthchecks for backend
- [ ] Dynamic quotes at the end of the page
