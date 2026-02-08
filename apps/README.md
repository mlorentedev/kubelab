 Applications - Source Code

This directory contains source code for all custom applications in the CubeLab platform.

 Structure

```
apps/
├── api/           Go REST API
├── blog/          Jekyll blog
├── web/           Astro website
├── wiki/          MkDocs documentation
├── nn/           nn workflow definitions
└── workers/       Background workers (Python)
```

 Development

Each application contains:
- Source code
- Dockerfile for container builds
- README.md with application-specific documentation

 Development Workflow

. Make changes in this directory (`apps/{app-name}/`)
. Build using toolkit or Docker:
   ```bash
    Using toolkit
   poetry run toolkit services build web

    Using Docker directly
   cd apps/web && docker build -t web .
   ```

. Deploy using configurations from `infra/stacks/apps/{app-name}/`

 Environment Files for Development

When developing locally, you may need to copy `.env.dev` files to app directories:

```bash
 Example: Copy web app env for local development
cp infra/stacks/apps/web/.env.dev apps/web/.env.dev
```

This allows Dockerfiles to access environment variables during build.

Note: `.env.` files in `apps/` are gitignored. Only commit `.env..example` files.

 Deployment Configurations

Deployment configurations (docker-compose, .env files) are located separately:

```
infra/stacks/apps/{app-name}/
├── compose.base.yml
├── compose.dev.yml
├── compose.staging.yml
├── compose.prod.yml
├── .env.dev
├── .env.staging
├── .env.prod
└── .env..example
```

See `infra/stacks/apps/README.md` for deployment documentation.

 Documentation

Each application has its own README with:
- Purpose and features
- Technology stack
- Build instructions
- Development notes
- Deployment references

 Related

- Deployment: `infra/stacks/apps/` - How to run applications
- Toolkit: `toolkit/cli/services.py` - CLI commands for app/service management
- Documentation: `docs/ARCHITECTURE.md` - Overall system architecture
