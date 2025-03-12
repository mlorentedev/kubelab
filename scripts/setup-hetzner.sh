#!/bin/bash

# Script to configure server on Hetzner
# Usage: ./setup-hetzner.sh [production|staging]

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check parameters
if [ "$#" -ne 1 ]; then
    echo -e "${RED}Error: You must specify the environment (production or staging).${NC}"
    echo "Usage: ./setup-hetzner.sh [production|staging]"
    exit 1
fi

ENV=$1

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: The environment must be 'production' or 'staging'.${NC}"
    echo "Usage: ./setup-hetzner.sh [production|staging]"
    exit 1
fi

# Prompt for server IP
echo -e "${YELLOW}Enter the server IP for $ENV:${NC}"
read SERVER_IP

# Check connectivity
echo -e "${BLUE}Verifying connectivity with $SERVER_IP...${NC}"
if ! ping -c 1 $SERVER_IP &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to server $SERVER_IP${NC}"
    exit 1
fi

# Define user and installation directory
if [ "$ENV" == "production" ]; then
    INSTALL_DIR="/opt/mlorente"
    DOMAIN="mlorente.dev"
else
    INSTALL_DIR="/opt/mlorente-staging"
    DOMAIN="staging.mlorente.dev"
fi

echo -e "${GREEN}Configuring $ENV server at $SERVER_IP...${NC}"
echo -e "${BLUE}Will use directory: $INSTALL_DIR${NC}"
echo -e "${BLUE}Will configure domain: $DOMAIN${NC}"

# Confirm before continuing
echo ""
echo -e "${YELLOW}Do you want to continue with the configuration? (y/n)${NC}"
read CONFIRM

if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo -e "${RED}Configuration canceled.${NC}"
    exit 1
fi

# Commands to execute on remote server
SSH_COMMANDS=$(cat <<EOF
#!/bin/bash

# Update system
echo "Updating system..."
apt update && apt upgrade -y

# Install necessary packages
echo "Installing necessary packages..."
sudo apt install -y \
    ufw \
    fail2ban \
    unattended-upgrades \
    apt-listchanges \
    software-properties-common \
    certbot \
    curl \
    git \
    docker.io \
    docker-compose

# Configure automatic security updates
echo "Configuring automatic security updates..."
sudo dpkg-reconfigure -plow unattended-upgrades

# Configure firewall
echo "Configuring firewall..."
ufw allow ssh
ufw allow http
ufw allow https
ufw --force enable

# Configure fail2ban
echo "Configuring fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban

# Create deployment user
echo "Creating deployer user..."
if ! id -u deployer &>/dev/null; then
    useradd -m -s /bin/bash deployer
    mkdir -p /home/deployer/.ssh
    chmod 700 /home/deployer/.ssh
    echo 'deployer ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/bin/docker-compose, /usr/bin/docker-compose-v2' > /etc/sudoers.d/deployer
    chmod 440 /etc/sudoers.d/deployer
fi

# Request SSH key for deployer user
echo "Please paste your SSH public key for the deployer user (end with an empty line):"
cat > /home/deployer/.ssh/authorized_keys

# Configure permissions
chown -R deployer:deployer /home/deployer/.ssh
chmod 600 /home/deployer/.ssh/authorized_keys

# Create application directory
echo "Creating application directory: $INSTALL_DIR"
mkdir -p $INSTALL_DIR
chown deployer:deployer $INSTALL_DIR

# Create certificate directory structure
mkdir -p $INSTALL_DIR/certbot/conf
mkdir -p $INSTALL_DIR/certbot/www
chown -R deployer:deployer $INSTALL_DIR

# Create initial .env file
cat > $INSTALL_DIR/.env <<EOL
# Environment: $ENV
# Generated on: $(date)
# WARNING: This is an initial file. It will be replaced during deployment.

ENV=$ENV
SITE_DOMAIN=$DOMAIN
EOL
chown deployer:deployer $INSTALL_DIR/.env

# Obtain initial certificates (optional)
echo "Do you want to obtain SSL certificates now? (y/n)"
read GET_CERTS

if [[ "\$GET_CERTS" == "y" || "\$GET_CERTS" == "Y" ]]; then
    echo "Obtaining SSL certificates for $DOMAIN..."
    certbot certonly --standalone --agree-tos --email admin@$DOMAIN -d $DOMAIN -d www.$DOMAIN
    mkdir -p $INSTALL_DIR/certbot/conf/$DOMAIN
    cp -L /etc/letsencrypt/live/$DOMAIN/* $INSTALL_DIR/certbot/conf/$DOMAIN/
    cp -r /etc/letsencrypt/archive/$DOMAIN/* $INSTALL_DIR/certbot/conf/$DOMAIN/
    chown -R deployer:deployer $INSTALL_DIR/certbot
fi

# Enable Docker to start on boot
systemctl enable docker
systemctl start docker

# Create basic docker-compose.yml
cat > $INSTALL_DIR/docker-compose.yml <<EOL
version: '3.8'

services:
  frontend:
    image: dockerhub-username/mlorente-frontend:latest
    restart: always
    ports:
      - "3000:4321"
    env_file:
      - .env
    networks:
      - app-network
    depends_on:
      - backend

  backend:
    image: dockerhub-username/mlorente-backend:latest
    restart: always
    env_file:
      - .env
    networks:
      - app-network

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    restart: always
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    depends_on:
      - frontend
      - backend
    networks:
      - app-network

  certbot:
    image: certbot/certbot
    restart: unless-stopped
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait \$\${!}; done;'"
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
EOL
chown deployer:deployer $INSTALL_DIR/docker-compose.yml

echo "======================================================"
echo "$ENV server configuration completed successfully!"
echo "======================================================"
echo "IP: $SERVER_IP"
echo "Deployment user: deployer"
echo "Installation directory: $INSTALL_DIR"
echo "Domain: $DOMAIN"
echo ""
echo "Next steps:"
echo "1. Configure secrets in GitHub"
echo "2. Run the CI/CD pipeline"
echo "3. Verify operation at $DOMAIN"
echo "======================================================"
EOF
)

# Connect to server and execute commands
echo -e "${BLUE}Connecting to server...${NC}"
echo "$SSH_COMMANDS" | ssh root@$SERVER_IP "bash -s"

echo -e "${GREEN}$ENV server configuration completed!${NC}"
echo "Server prepared for automated deployments."