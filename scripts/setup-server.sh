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

# Load environment variables
ENV_FILE="$SCRIPT_DIR/../.env"
load_env_file "$ENV_FILE"

# Specifically handle SSH_PUBLIC_KEY for multiline content
if [ -z "$SSH_PUBLIC_KEY" ]; then
    log_error "SSH_PUBLIC_KEY environment variable is not set. Please configure it in your .env file."
    log_info "To set SSH_PUBLIC_KEY, add the following to your .env file:"
    log_info "SSH_PUBLIC_KEY=\"your_public_key_here\""
    log_info "Replace 'your_public_key_here' with your actual public key."
    exit 1
fi

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

# Commands to configure the server
TEMP_SCRIPT=$(mktemp /tmp/server_setup_XXXXXX.sh)
cat > "$TEMP_SCRIPT" <<EOF
#!/bin/bash
set -e

# Variables
INSTALL_DIR="$DEPLOY_DIR"
DOMAIN="$DOMAIN"
ENV="$ENV"
SSH_PUBLIC_KEY="$SSH_PUBLIC_KEY"

echo "=== Starting server configuration ==="

# Update system
echo "Updating system..."
apt update && apt upgrade -y

# Install required packages
echo "Installing required packages..."
apt install -y docker.io docker-compose curl git fail2ban ufw certbot \
    unattended-upgrades apt-listchanges software-properties-common python3-certbot-nginx

# Configure automatic security updates
echo "Configuring automatic security updates..."
dpkg-reconfigure -plow unattended-upgrades

# Configure firewall
echo "Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https
ufw --force enable

# Configure fail2ban
echo "Configuring fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban

echo "Creating deployer user..."
if ! id -u deployer &>/dev/null; then
    useradd -m -s /bin/bash deployer
    mkdir -p /home/deployer/.ssh
    chmod 700 /home/deployer/.ssh

    # Disable password authentication and root login
    echo "PasswordAuthentication no" >> /etc/ssh/sshd_config
    echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config
    echo "AuthorizedKeysFile .ssh/authorized_keys" >> /etc/ssh/sshd_config
    systemctl restart ssh
    
    # Add SSH key for deployer user from environment variable
    if [ -z "$SSH_PUBLIC_KEY" ]; then
        echo "Error: SSH_PUBLIC_KEY environment variable is not set."
        exit 1
    fi

    touch /home/deployer/.ssh/authorized_keys
    echo "$SSH_PUBLIC_KEY" > /home/deployer/.ssh/authorized_keys
    chmod 600 /home/deployer/.ssh/authorized_keys
    chown deployer:deployer /home/deployer/.ssh/authorized_keys
    chown -R deployer:deployer /home/deployer/.ssh

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
mkdir -p \$INSTALL_DIR/docker/nginx/conf.d

# Create initial .env file
echo "Creating initial .env..."
cat > \$INSTALL_DIR/.env <<EOL
# Environment: \$ENV
# Generated on: \$(date)
# WARNING: This file will be replaced during deployment

ENV=\$ENV
SITE_DOMAIN=\$DOMAIN
EOL

# Obtain SSL certificates
echo "Do you want to obtain SSL certificates for \$DOMAIN now? (y/n)"
read GET_CERTS

if [[ "\$GET_CERTS" == "y" || "\$GET_CERTS" == "Y" ]]; then
    echo "Obtaining SSL certificates for \$DOMAIN..."
    # Stop any running web servers on port 80
    systemctl stop nginx 2>/dev/null || true
    
    # Use standalone mode to obtain certificates
    certbot certonly --standalone --agree-tos --email admin@\$DOMAIN -d \$DOMAIN -d www.\$DOMAIN
    
    # Copy certificates to the right location
    mkdir -p \$INSTALL_DIR/certbot/conf/live/\$DOMAIN
    cp -L /etc/letsencrypt/live/\$DOMAIN/fullchain.pem \$INSTALL_DIR/certbot/conf/live/\$DOMAIN/
    cp -L /etc/letsencrypt/live/\$DOMAIN/privkey.pem \$INSTALL_DIR/certbot/conf/live/\$DOMAIN/
    cp -L /etc/letsencrypt/live/\$DOMAIN/chain.pem \$INSTALL_DIR/certbot/conf/live/\$DOMAIN/
    cp -L /etc/letsencrypt/live/\$DOMAIN/cert.pem \$INSTALL_DIR/certbot/conf/live/\$DOMAIN/
    
    # Copy archive and renewal configuration
    mkdir -p \$INSTALL_DIR/certbot/conf/archive/\$DOMAIN
    cp -r /etc/letsencrypt/archive/\$DOMAIN/* \$INSTALL_DIR/certbot/conf/archive/\$DOMAIN/
    mkdir -p \$INSTALL_DIR/certbot/conf/renewal
    cp /etc/letsencrypt/renewal/\$DOMAIN.conf \$INSTALL_DIR/certbot/conf/renewal/
    
    echo "SSL certificates obtained and copied to Docker volumes"
else
    echo "Skipping SSL certificate generation. You'll need to set up certificates later."
fi

# Configure permissions
chown -R deployer:deployer \$INSTALL_DIR
chmod -R 755 \$INSTALL_DIR

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

# Final instructions
echo "To deploy your application, run the deployment script from your CI/CD pipeline"
echo "or copy the configuration files from your repository and then run:"
echo "cd \$INSTALL_DIR && docker-compose up -d"
EOF

# Connect to the server and run configuration
log_info "Connecting to server and running configuration..."
scp -o StrictHostKeyChecking=accept-new -i "$SSH_KEY_PATH" "$TEMP_SCRIPT" "root@$SERVER_IP:/tmp/server_setup.sh"
ssh -i "$SSH_KEY_PATH" "root@$SERVER_IP" "bash /tmp/server_setup.sh"
ssh -o StrictHostKeyChecking=accept-new -i "$SSH_KEY_PATH" "root@$SERVER_IP" "rm /tmp/server_setup.sh"
rm "$TEMP_SCRIPT"

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

# Ask if we want to copy configuration files now
if confirm_action "Do you want to copy your configuration files (docker-compose.yml, nginx config) to the server now?"; then
    log_info "Copying configuration files to server..."
    
    # Copy docker-compose.yml
    if [ -f "$SCRIPT_DIR/../docker-compose.yml" ]; then
        scp -i "$SSH_KEY_PATH" "$SCRIPT_DIR/../docker-compose.yml" "$SERVER_ALIAS:$DEPLOY_DIR/"
        log_success "docker-compose.yml copied successfully."
    else
        log_warning "docker-compose.yml not found in the repository root."
    fi
    
    # Copy nginx configuration
    if [ -d "$SCRIPT_DIR/../docker/nginx" ]; then
        scp -r -i "$SSH_KEY_PATH"  "$SCRIPT_DIR/../docker/nginx" "$SERVER_ALIAS:$DEPLOY_DIR/docker/"
        # Replace domain placeholder if exists
        ssh "$SERVER_ALIAS" "cd $DEPLOY_DIR && sed -i \"s/\\\${DOMAIN}/$DOMAIN/g\" docker/nginx/conf.d/*.conf"
        log_success "Nginx configuration copied and updated successfully."
    else
        log_warning "Nginx configuration directory not found."
    fi
fi

log_success "Server configured successfully."
log_info "You can now connect simply with: ssh $SERVER_ALIAS"
log_info "Next steps: deploy the application through the CD pipeline"