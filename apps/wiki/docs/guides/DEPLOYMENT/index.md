# Deployment

Server setup and deployment procedures for mlorente.dev.

## Server Requirements

**Minimum specs:**
- 2 vCPU, 4GB RAM, 40GB SSD
- Ubuntu 22.04 LTS (recommended)
- Docker, Docker Compose, Git

**Network:**
- Ports: 80, 443, 22
- DNS records pointing to server IP:
  - mlorente.dev
  - blog.mlorente.dev  
  - api.mlorente.dev

## Server Setup

### 1. Create deploy user

```bash
# On server as root
adduser mlorente-deployer
usermod -aG docker,sudo mlorente-deployer
echo "mlorente-deployer ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/mlorente-deployer
```

### 2. SSH keys

```bash
# Local machine
ssh-keygen -t ed25519 -f ~/.ssh/mlorente-deploy
ssh-copy-id -i ~/.ssh/mlorente-deploy.pub mlorente-deployer@SERVER_IP

# Add to ~/.ssh/config
Host mlorente-prod
  HostName SERVER_IP
  User mlorente-deployer
  IdentityFile ~/.ssh/mlorente-deploy
```

### 3. Install dependencies

```bash
ssh mlorente-prod

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# Install Docker Compose
sudo apt update
sudo apt install -y git make curl
```

## Deployment

### First deployment

```bash
# Clone repo on server
cd /opt
sudo git clone <repo-url> mlorente.dev
sudo chown -R mlorente-deployer:mlorente-deployer mlorente.dev
cd mlorente.dev

# Setup environment
cp .env.production.example .env.production
# Edit .env.production with your values

# Deploy
make deploy ENV=production
```

### Regular deployments

```bash
# From local machine
make deploy ENV=production

# Or on server
git pull origin master
make deploy ENV=production
```

## Environment Files

Create `.env.production` with:

```env
# Required
DOMAIN=mlorente.dev
EMAIL=admin@mlorente.dev

# Optional
TRAEFIK_DASHBOARD=false
MONITORING_ENABLED=true
```

## SSL Certificates

Traefik handles SSL automatically with Let's Encrypt. Ensure:
- DNS records are correctly configured
- Ports 80/443 are accessible
- Email is set for Let's Encrypt notifications

## Troubleshooting

**SSL issues:**
```bash
make logs APP=traefik
```

**Check services:**
```bash
make status
```

**Service not starting:**
```bash
docker ps -a
docker logs <container_name>
```

**Disk space:**
```bash
docker system prune -a
```

## Rollback

```bash
make emergency-rollback ENV=production
```

## Monitoring

Access monitoring at:
- https://grafana.mlorente.dev (if enabled)
- https://traefik.mlorente.dev/dashboard (if enabled)

Check logs:
```bash
make logs ENV=production
make logs APP=api ENV=production
```