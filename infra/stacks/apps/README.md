 Application Deployments

This directory contains deployment configurations for all custom applications.

 Structure

```
infra/stacks/apps/
├── api/
│   ├── compose.base.yml
│   ├── compose.dev.yml
│   ├── compose.staging.yml
│   └── compose.prod.yml
├── blog/
├── web/
├── wiki/
├── nn/
└── workers/
```

Configuration is centralized in `infra/config/`:
- Values: `infra/config/values/{common,dev,staging,prod}.yaml`
- Secrets: `infra/config/secrets/{env}.enc.yaml` (SOPS-encrypted)

 Deployment

 Using Toolkit

```bash
 Start application in development
poetry run toolkit apps up web

 Start in staging
ENVIRONMENT=staging poetry run toolkit apps up web

 View logs
poetry run toolkit apps logs web

 Stop application
poetry run toolkit apps down web
```

 Using Docker Compose Directly

```bash
 Development
cd infra/stacks/apps/web
docker compose -f compose.base.yml -f compose.dev.yml up -d

 Staging
docker compose -f compose.base.yml -f compose.staging.yml up -d

 Production
docker compose -f compose.base.yml -f compose.prod.yml up -d
```

 Configuration

All configuration is centralized (not per-stack):

- **Values**: `infra/config/values/{common,dev,staging,prod}.yaml` - YAML configuration per environment
- **Secrets**: `infra/config/secrets/{env}.enc.yaml` - SOPS-encrypted secrets (age key)

The `compose.base.yml` defines service defaults, and `compose.{env}.yml` overlays provide environment-specific overrides (images, ports, volumes, resource limits).

 Editing Configuration

```bash
 Edit environment values
vim infra/config/values/dev.yaml

 Edit encrypted secrets (requires age key)
sops infra/config/secrets/dev.enc.yaml
```

 Source Code

Application source code is located separately:

```
apps/{app-name}/
├── src/               Source code
├── Dockerfile         Build instructions
└── README.md          Development docs
```

See `apps/README.md` for development documentation.

 Environments

 Development (dev)
- Location: Local machine
- Purpose: Development and testing
- Access: localhost
- Services: Traefik (HTTP only)

 Staging (staging)
- Location: CubeLab homelab (Raspberry Pi)
- Purpose: Pre-production testing
- Access: VPN (WireGuard) + .staging.mlorente.dev
- Services: Full stack with CoreDNS gateway

 Production (prod)
- Location: Hetzner VPS
- Purpose: Live production
- Access: Public .mlorente.dev
- Services: Full stack with HTTPS (Let's Encrypt)

 Documentation

- `docs/ARCHITECTURE.md` - System architecture
- `docs/HOW-TO.md` - Quick command reference
- `docs/TOOLKIT.md` - Toolkit CLI guide
