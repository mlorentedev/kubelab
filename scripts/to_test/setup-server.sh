#!/bin/bash
# setup-server.sh - Configure server for mlorente.dev deployment
# Usage: ./setup-server.sh <server_ip> <environment>
# Example: ./setup-server.sh 123.456.789.0 production
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh" "ping" "ssh-keygen"

# Check parameters
if [ "$#" -ne 2 ]; then
    exit_error "Incorrect usage. Required: <server_ip> <environment>\nExample: $0 123.456.789.0 production"
fi

SERVER_IP=$1
ENV=$2

# Validate environment
validate_environment "$ENV"

# Check server connectivity
log_info "Checking connectivity with $SERVER_IP..."
if ! ping -c 1 "$SERVER_IP" &> /dev/null; then
    exit_error "Cannot connect to server $SERVER_IP. Please check if it's online."
fi

log_info "Configuring $ENV server at $SERVER_IP"
log_info "Installation directory: $DEPLOY_DIR"
log_info "Domain: $DOMAIN"

# Confirm action
if ! confirm_action "This will configure the server for deployment. Continue?"; then
    exit 0
fi

# Ensure SSH key exists
ensure_ssh_key

# Commands to configure the server
SERVER_SETUP=$(cat <<EOF
#!/bin/bash
set -e

# Variables
INSTALL_DIR="$DEPLOY_DIR"
DOMAIN="$DOMAIN"
ENV="$ENV"

echo "=== Starting server configuration ==="

# Update system
echo "Updating system..."
apt update && apt upgrade -y

# Install required packages
echo "Installing required packages..."
apt install -y docker.io docker-compose curl git fail2ban ufw certbot \
    unattended-upgrades apt-listchanges software-properties-common

# Configure automatic security updates
echo "Configuring automatic security updates..."
dpkg-reconfigure -plow unattended-upgrades

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
    
    # Add SSH key for deployer user
    echo "Paste the SSH public key for the deployer user (press Ctrl+D when done):"
    cat > /home/deployer/.ssh/authorized_keys
    
    # Configure sudo access for Docker
    echo 'deployer ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/bin/docker-compose, /usr/bin/systemctl' > /etc/sudoers.d/deployer
    chmod 440 /etc/sudoers.d/deployer
fi

# Configure permissions
chown -R deployer:deployer /home/deployer/.ssh
chmod 600 /home/deployer/.ssh/authorized_keys

# Create directories for the application
echo "Creating directories for the application..."
mkdir -p \$INSTALL_DIR
mkdir -p \$INSTALL_DIR/certbot/conf
mkdir -p \$INSTALL_DIR/certbot/www
mkdir -p \$INSTALL_DIR/backups

# Create initial .env file
echo "Creating initial .env..."
cat > \$INSTALL_DIR/.env <<EOL
# Environment: \$ENV
# Generated on: \$(date)
# WARNING: This file will be replaced during deployment

ENV=\$ENV
SITE_DOMAIN=\$DOMAIN
EOL

# Create basic docker-compose.yml
echo "Creating basic docker-compose.yml..."
cat > \$INSTALL_DIR/docker-compose.yml <<EOL
version: '3.8'

services:
  frontend:
    image: mlorentedev/mlorente-frontend:\${TAG:-latest}
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
    image: mlorentedev/mlorente-backend:\${TAG:-latest}
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
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait \\\$\\\$!; done;'"
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
EOL

# Get initial certificates (optional)
echo "Do you want to obtain SSL certificates now? (y/n)"
read GET_CERTS

if [[ "\$GET_CERTS" == "y" || "\$GET_CERTS" == "Y" ]]; then
    echo "Obtaining SSL certificates for \$DOMAIN..."
    certbot certonly --standalone --agree-tos --email admin@\$DOMAIN -d \$DOMAIN -d www.\$DOMAIN
    
    mkdir -p \$INSTALL_DIR/certbot/conf/\$DOMAIN
    cp -L /etc/letsencrypt/live/\$DOMAIN/* \$INSTALL_DIR/certbot/conf/\$DOMAIN/
    cp -r /etc/letsencrypt/archive/\$DOMAIN/* \$INSTALL_DIR/certbot/conf/\$DOMAIN/
fi

# Configure permissions
chown -R deployer:deployer \$INSTALL_DIR

# Configure Docker to start on boot
systemctl enable docker
systemctl start docker

# Secure SSH configuration
echo "Securing SSH configuration..."
sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh

echo "======================================"
echo "Server configuration completed."
echo "======================================"
echo "IP: $SERVER_IP"
echo "Environment: \$ENV"
echo "Deployment user: deployer"
echo "Directory: \$INSTALL_DIR"
echo "Domain: \$DOMAIN"
echo "======================================"
EOF
)

# Connect to the server and run configuration
log_info "Connecting to server and running configuration..."
ssh -o StrictHostKeyChecking=accept-new "root@$SERVER_IP" "bash -s" <<< "$SERVER_SETUP"

# Generate configuration file for simplified SSH access
log_info "Configuring simplified SSH access..."

SSH_CONFIG_FILE="$HOME/.ssh/config"
SSH_ENTRY="Host $SERVER_ALIAS
    HostName $SERVER_IP
    User deployer
    IdentityFile $SSH_KEY_PATH
    StrictHostKeyChecking no"

if [ -f "$SSH_CONFIG_FILE" ]; then
    # Check if an entry for this server already exists
    if grep -q "Host $SERVER_ALIAS" "$SSH_CONFIG_FILE"; then
        log_warning "Updating existing SSH configuration..."
        sed -i.bak "/Host $SERVER_ALIAS/,/StrictHostKeyChecking/d" "$SSH_CONFIG_FILE"
    fi
    echo "$SSH_ENTRY" >> "$SSH_CONFIG_FILE"
else
    log_info "Creating SSH configuration file..."
    echo "$SSH_ENTRY" > "$SSH_CONFIG_FILE"
    chmod 600 "$SSH_CONFIG_FILE"
fi

log_success "Server configured successfully."
log_info "You can now connect simply with: ssh $SERVER_ALIAS"
log_info "Next steps:"
log_info "1. Update environment variables with: ./update-env.sh $ENV"
log_info "2. Deploy the application with: ./deploy.sh $ENV"