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

2. Prepare the environment:

   ```bash
   # Prepare the environment
   ./scripts/dev-setup.sh

   # Configure GitHub secrets for CI/CD
    ./scripts/setup-github-secrets.sh

   # Configure development environment
   ./scripts/setup-hetzner.sh staging

   # Configure production environment
   ./scripts/setup-hetzner.sh production
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

This process includes tests, builds, and deployment steps.

#### Manual Deployment

If you need to deploy manually, you can use the following commands in the production server:

```bash
cd /opt/mlorente
docker-compose pull
docker-compose up -d
```

#### Environment Variables

Environment variables are managed in `opt/mlorente/.env`. This file is generated during deployment, but can be manually edited if needed.

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

## Aditional notes

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name and its language parameter.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

The `src/content/` directory contains "collections" of related Markdown and MDX documents.
The `src/content/config.ts` file adds the `slug` key as a property to the collections. This is the slug that will be used in the header, blogs list page and as canonical and alternate URLs.

Any static assets, like images, can be placed in the `public/` directory.

To run this project, need to create a file `.env.dev` in the root directory with the necessary environment variables:

```env
# Example .env.dev file
ENV=development

# Application
SITE_TITLE=mlorente.dev
SITE_DESCRIPTION=Blog personal de Manuel Lorente
SITE_DOMAIN=localhost
SITE_URL=http://localhost:3000
SITE_MAIL=mlorentedev@gmail.com
SITE_AUTHOR=Manuel Lorente
SITE_KEYWORDS=devops, cloud, kubernetes, aws, azure, python, go

# Social Media
TWITTER_URL=https://twitter.com/mlorentedev
YOUTUBE_URL=https://youtube.com/@mlorentedev
GITHUB_URL=https://github.com/mlorentedev
CALENDLY_URL=
BUY_ME_A_COFFEE_URL=

# Analytics
GOOGLE_ANALYTICS_ID=

# Features
ENABLE_HOMELABS=true
ENABLE_BLOG=true
ENABLE_CONTACT=true

# Backend
BACKEND_URL=http://backend:8080

# Beehiiv
BEEHIIV_API_KEY=dev_key
BEEHIIV_PUB_ID=dev_pub

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_SECURE=false
EMAIL_USER=
EMAIL_PASS=
```

## HETZNER

This project is designed to be deployed on Hetzner Cloud. You can use the `scripts/setup-hetzner.sh` script to configure your environment.

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
- [ ] Add homelab section: learning-path, homelabs, etc. similar to Collabnix
- [ ] Slack community integration with the API
- [ ] Most recent RRSS in some section - dynamic with CI/CD
- [ ] Indexed search by tags
- [ ] Copy in all pages
- [ ] Simple and minimalistic design
- [ ] Add analytics
- [ ] Dynamic quotes at the end of the page
