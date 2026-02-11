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

 Configuration

Environment configuration is centralized in `infra/config/`:

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml` - YAML configuration per environment
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` - SOPS-encrypted secrets (age key)

No `.env` files are used. All configuration is injected through compose overlays and the values/secrets system.

 Deployment Configurations

Deployment configurations (compose overlays) are located separately:

```
infra/stacks/apps/{app-name}/
├── compose.base.yml           Service defaults
├── compose.dev.yml            Dev environment overlay
├── compose.staging.yml        Staging environment overlay
└── compose.prod.yml           Production environment overlay
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
