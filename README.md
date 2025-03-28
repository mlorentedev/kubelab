# My site

My personal site built with Jekyll, containerized with Docker, and deployed using Traefik for SSL termination and reverse proxy.

## Features

- Static website built with Jekyll
- Fully responsive design
- Containerized with Docker
- Automated builds via GitHub Actions
- SSL certificates managed by Traefik via Let's Encrypt
- Content categories and tags
- Reading time estimation
- Markdown support for content
- SEO optimized

## Project Structure

```bash
├── .github/                       # GitHub Actions workflow configurations
├── docker-compose.local.yml       # Local environment docker-compose config
├── docker-compose.production.yml  # Production environment config
├── docker-compose.staging.yml     # Staging environment config
├── docker-compose.traefik.yml     # Traefik proxy configuration
├── .env.example                   # Example environment variables
├── jekyll                         # Main Jekyll site directory
│   ├── _config.yml                # Jekyll configuration
│   ├── _data                      # Data files for Jekyll
│   ├── _includes                  # Template includes
│   ├── _layouts                   # Page layouts
│   ├── _posts                     # Blog post content
│   ├── 404.html                   # 404 error page
│   ├── aboutme.html               # About me page
│   ├── assets                     # Static assets
│   │   ├── css                    # Stylesheets
│   │   ├── cv                     # Resume/CV files
│   │   ├── img                    # Image assets
│   │   ├── js                     # JavaScript files
│   │   └── pdf                    # PDF documents
│   ├── Dockerfile                 # Docker image definition
│   ├── Gemfile                    # Ruby dependencies
│   └── index.html                 # Site homepage
├── README.md                      # Project documentation
├── scripts                        # Utility scripts
│   ├── cleanup.sh                 # Resource cleanup
│   ├── deploy.sh                  # Deployment script
│   ├── generate-traefik-config.sh # Traefik config generator
│   ├── generate-traefik-credentials.sh # Auth credential generator
│   └── utils.sh                   # Shared utility functions
└── traefik                        # Traefik configuration templates
    ├── traefik.template.http.yml  # HTTP configuration template
    └── traefik.template.https.yml # HTTPS configuration template
```

## Prerequisites

- Docker and Docker Compose
- Git
- A DockerHub account for storing container images
- A domain name (for staging and production environments)
- A server with SSH access (for staging and production)

## Local Development

To run the project locally:

1. Clone the repository

2. Create a local environment file

   ```bash
   cp .env.example .env.local
   ```

3. Edit `.env.local` with your local configuration

   ```.env.local
   # Site
   ENVIRONMENT=local
   ARTIFACT_NAME=blog-site
   DOMAIN=localhost
   EMAIL=your-email@example.com

   # DockerHub
   DOCKERHUB_USERNAME=your-dockerhub-username
   DOCKERHUB_TOKEN=your-dockerhub-token

   # Environment
   ENVIRONMENT=local
   TRAEFIK_DASHBOARD=true
   TRAEFIK_INSECURE=true
   ```

4. Copy to `.env` file

   ```bash
   cp .env.local .env
   ```

5. Change url in `_config.yml` to match your local domain

   ```yaml
    url: ""
   ```

6. Launch the services

   ```bash
   docker network create traefik_network
   ./scripts/generate-traefik-config.sh   
   docker-compose -f docker-compose.local.yml up -d --build
   ```

7. Access your site at <http://localhost>

## Deployment

Prior to deploying to staging or production, ensure you have created the necessary environment files and have access to your server based on the example `.env.example` file.

First need to generate a password for Traefik dashboard and set it in the environment files. You can use the following script to generate the user and password for the Traefik dashboard:

```bash
./scripts/generate-traefik-credentials.sh
```

1. Copy all necessary files to your staging server. You can use `scp` or any other file transfer method. For example:

   ```bash
   ssh mlorente-deployer "mkdir -p /opt/mlorente.dev"
   ssh mlorente-deployer "rm -f /opt/mlorente.dev/traefik/traefik.yml"
   scp -r -p scripts/* mlorente-deployer:/opt/mlorente.dev/scripts/
   scp -r -p traefik/* mlorente-deployer:/opt/mlorente.dev/traefik/
   scp -p .env.staging mlorente-deployer:/opt/mlorente.dev/
   scp -p .env.production mlorente-deployer:/opt/mlorente.dev/
   scp -p docker-compose.staging.yml mlorente-deployer:/opt/mlorente.dev/
   scp -p docker-compose.production.yml mlorente-deployer:/opt/mlorente.dev/
   scp -p docker-compose.traefik.yml mlorente-deployer:/opt/mlorente.dev/
   ```

2. Access your server via SSH and navigate to your project directory.

   ```bash
   ssh user@server
   cd /opt/mlorente.dev
   ```

3. Create the Docker network for Traefik if it doesn't exist

   ```bash
   docker network create traefik_network
   ```

4. Make the scripts executable.

   ```bash
   chmod a+x scripts/*.sh
   ```

5. Run the deployment script for common services.

   ```bash
   ./scripts/deploy.sh deploy common
   ```

6. Run the deployment script for staging or production

   ```bash
   ./scripts/deploy.sh deploy [staging|production|all]
   ```

Resources can be cleaned up by running the following command:

```bash
./scripts/cleanuo.sh
```

This will set up the environment for the specified deployment, including copying the appropriate `.env` file, generating the Traefik configuration, and starting the Docker containers.

To test locally the staging environment, you need to copy the certificate generated by Traefik to your local machine and then use it to test your local environment.

```bash
scp mlorente-deployer:/opt/mlorente.dev/traefik/acme.json ~/Downloads/acme.json
cat ~/Downloads/acme.json | jq -r '.myresolver.Certificates[0].certificate' | base64 -d > ~/Downloads/staging-cert.crt
cat ~/Downloads/acme.json | jq -r '.myresolver.Certificates[0].key' | base64 -d > ~/Downloads/staging-key.key
sudo cp ~/Downloads/staging-cert.crt ~/Downloads/staging-key.key /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Then, you can use this certificate to test your local environment with the staging configuration.

By default any browser accepts the self-signed certificate generated by Traefik for staging. If you want to test it need to add the certificate to your browser's trusted certificates or launch the browser with the `--ignore-certificate-errors` flag (not recommended for production).

```bash
    google-chrome --ignore-certificate-errors --user-data-dir=/tmp/chrome-test
```

**Note**: For production, we use the Let's Encrypt production ACME server rather than the staging one. Be careful not to exceed their rate limits.

To access the Traefik dashboard, navigate to `https://traefik.mlorente.dev:8080/dashboard/` (or `https://SERVER-IP:8080/dashboard/` for secure environments). The dashboard will require basic authentication using the credentials you generated earlier.

## CI/CD Pipeline

The project includes a GitHub Actions workflow that:

1. Builds the Jekyll site
2. Creates a Docker image
3. Pushes the image to DockerHub
4. Creates deployment artifacts
5. Generates a new release

The workflow is triggered by:

- Push to the `master` branch
- Daily at midnight `(cron: '0 0 * * *')`
- Manual execution via workflow_dispatch

### Versioning

The project follows Semantic Versioning through commit messages:

- **Major version** increments with breaking changes:
  - Messages containing "BREAKING CHANGE:" or "!:"
  - Example: `feat!: breaking change description`

- **Minor version** increments with new features:
  - Messages starting with `feat:`
  - Example: `feat: add new search functionality`

- **Patch version** increments with fixes/small changes:
  - Messages starting with `fix:`, `docs:`, `chore:`, `style:`, etc.
  - Example: `fix: correct contact form error`

See [CONTRIBUTING.md](CONTRIBUTING.md) for more details on commit message conventions and versioning.

## Troubleshooting

If you encounter issues with the deployment:

1. Check container status

   ```bash
   docker ps
   ```

2. Review container logs

   ```bash
   docker-compose logs jekyll
   docker-compose logs traefik
   ```

3. Verify Traefik configuration

   ```bash
   cat traefik/traefik.yml
   ```

4. Check SSL certificates  
    If you are using Traefik with Let's Encrypt, ensure that the `acme.json` file has the correct permissions and contains valid certificates:

   ```bash
   docker-compose exec traefik cat /acme.json
   ```

5. Restart the containers  
    If you make changes to the configuration or environment variables, you may need to restart the containers:

   ```bash
   docker-compose down
   docker-compose up -d
   ```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
