 Application Deployments

This directory contains deployment configurations for all custom applications.

 Structure

```
infra/compose/apps/
├── api/
│   ├── docker-compose.dev.yml
│   ├── docker-compose.staging.yml
│   ├── docker-compose.prod.yml
│   ├── .env.dev
│   ├── .env.staging
│   ├── .env.prod
│   └── .env..example
├── blog/
├── web/
├── wiki/
├── nn/
└── workers/
```

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
cd infra/compose/apps/web
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d

 Staging
docker compose -f docker-compose.staging.yml --env-file .env.staging up -d

 Production
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

 Environment Files

Each application has environment files per environment:

- `.env.dev` - Development (local)
- `.env.staging` - Staging (CubeLab homelab)
- `.env.prod` - Production (Hetzner VPS)
- `.env..example` - Templates (committed to git)

 Creating Environment Files

If `.env.` files don't exist, copy from examples:

```bash
cd infra/compose/apps/web
cp .env.dev.example .env.dev
vim .env.dev   Edit with actual values
```

 Generating New Examples

After updating environment variables, generate new examples:

```bash
poetry run toolkit tools env-examples dev
```

This creates sanitized `.env..example` files safe for git.

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
