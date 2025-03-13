#!/bin/bash
# setup-server.sh - Configure server on Hetzner
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -ne 2 ]; then
    echo -e "${RED}Error: Incorrect usage.${NC}"
    echo "Usage: $0 <server_ip> <environment>"
    echo "Example: $0 123.456.789.0 production"
    exit 1
fi

SERVER_IP=$1
ENV=$2

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Check connectivity
echo -e "${BLUE}Checking connectivity with $SERVER_IP...${NC}"
if ! ping -c 1 $SERVER_IP &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to server $SERVER_IP${NC}"
    exit 1
fi

# Define installation directory based on environment
if [ "$ENV" == "production" ]; then
    INSTALL_DIR="/opt/mlorente"
    DOMAIN="mlorente.dev"
else
    INSTALL_DIR="/opt/mlorente-staging"
    DOMAIN="staging.mlorente.dev"
fi

echo -e "${GREEN}Configuring $ENV server at $SERVER_IP${NC}"
echo -e "${BLUE}Installation directory: $INSTALL_DIR${NC}"
echo -e "${BLUE}Domain: $DOMAIN${NC}"

# Confirm action
echo -e "${YELLOW}Are you sure you want to continue? (y/n)${NC}"
read confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo -e "${RED}Operation cancelled.${NC}"
    exit 0
fi

# Generate SSH key if it doesn't exist
SSH_KEY="$HOME/.ssh/id_rsa_mlorente"
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${YELLOW}SSH key not found. Do you want to generate a new one? (y/n)${NC}"
    read gen_key
    if [[ "$gen_key" == "y" || "$gen_key" == "Y" ]]; then
        echo -e "${BLUE}Generating new SSH key...${NC}"
        ssh-keygen -t rsa -b 4096 -f "$SSH_KEY" -N ""
        echo -e "${GREEN}SSH key generated: $SSH_KEY${NC}"
    else
        echo -e "${YELLOW}Please provide the path to your SSH key:${NC}"
        read SSH_KEY
        if [ ! -f "$SSH_KEY" ]; then
            echo -e "${RED}Error: Cannot find SSH key at $SSH_KEY${NC}"
            exit 1
        fi
    fi
fi

# Show and copy public key
echo -e "${YELLOW}SSH public key (copy this key):${NC}"
cat "${SSH_KEY}.pub"
echo ""
echo -e "${YELLOW}Press Enter when you've copied the key...${NC}"
read

# Commands to configure the server
SERVER_SETUP=$(cat <<'EOF'
#!/bin/bash
# Update system
echo "Updating system..."
apt update && apt upgrade -y

# Install required packages
echo "Installing required packages..."
apt install -y docker.io docker-compose curl git fail2ban ufw certbot

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
    
    # Request SSH key for deployer user
    echo "Paste the SSH public key for the deployer user (press Ctrl+D when done):"
    cat > /home/deployer/.ssh/authorized_keys
    
    echo 'deployer ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/bin/docker-compose' > /etc/sudoers.d/deployer
    chmod 440 /etc/sudoers.d/deployer
fi

# Configure permissions
chown -R deployer:deployer /home/deployer/.ssh
chmod 600 /home/deployer/.ssh/authorized_keys

# Create directories for the application
echo "Creating directories for the application..."
mkdir -p INSTALL_DIR
mkdir -p INSTALL_DIR/certbot/conf
mkdir -p INSTALL_DIR/certbot/www

# Create initial .env file
echo "Creating initial .env..."
cat > INSTALL_DIR/.env <<EOL
# Environment: ENV
# Generated on: $(date)
# WARNING: This file will be replaced during deployment

ENV=ENV
SITE_DOMAIN=DOMAIN
EOL

# Get initial certificates (optional)
echo "Do you want to obtain SSL certificates now? (y/n)"
read GET_CERTS

if [[ "$GET_CERTS" == "y" || "$GET_CERTS" == "Y" ]]; then
    echo "Obtaining SSL certificates for DOMAIN..."
    certbot certonly --standalone --agree-tos --email admin@DOMAIN -d DOMAIN -d www.DOMAIN
    
    mkdir -p INSTALL_DIR/certbot/conf/DOMAIN
    cp -L /etc/letsencrypt/live/DOMAIN/* INSTALL_DIR/certbot/conf/DOMAIN/
    cp -r /etc/letsencrypt/archive/DOMAIN/* INSTALL_DIR/certbot/conf/DOMAIN/
fi

# Configure permissions
chown -R deployer:deployer INSTALL_DIR

# Configure Docker to start on boot
systemctl enable docker
systemctl start docker

echo "======================================"
echo "Server configuration completed."
echo "======================================"
echo "IP: SERVER_IP"
echo "Environment: ENV"
echo "Deployment user: deployer"
echo "Directory: INSTALL_DIR"
echo "Domain: DOMAIN"
echo "======================================"
EOF
)

# Replace variables in the script
SERVER_SETUP=${SERVER_SETUP//INSTALL_DIR/$INSTALL_DIR}
SERVER_SETUP=${SERVER_SETUP//ENV/$ENV}
SERVER_SETUP=${SERVER_SETUP//DOMAIN/$DOMAIN}
SERVER_SETUP=${SERVER_SETUP//SERVER_IP/$SERVER_IP}

# Connect to the server and run configuration
echo -e "${BLUE}Connecting to server...${NC}"
ssh -o StrictHostKeyChecking=accept-new root@$SERVER_IP "bash -s" <<< "$SERVER_SETUP"

# Generate configuration file for simplified SSH access
echo -e "${BLUE}Configuring simplified SSH access...${NC}"

SSH_CONFIG_FILE="$HOME/.ssh/config"
SSH_ENTRY="Host mlorente-$ENV
    HostName $SERVER_IP
    User deployer
    IdentityFile $SSH_KEY
    StrictHostKeyChecking no"

if [ -f "$SSH_CONFIG_FILE" ]; then
    # Check if an entry for this server already exists
    if grep -q "Host mlorente-$ENV" "$SSH_CONFIG_FILE"; then
        echo -e "${YELLOW}Updating existing SSH configuration...${NC}"
        sed -i.bak "/Host mlorente-$ENV/,/StrictHostKeyChecking/d" "$SSH_CONFIG_FILE"
    fi
    echo "$SSH_ENTRY" >> "$SSH_CONFIG_FILE"
else
    echo -e "${YELLOW}Creating SSH configuration file...${NC}"
    echo "$SSH_ENTRY" > "$SSH_CONFIG_FILE"
    chmod 600 "$SSH_CONFIG_FILE"
fi

echo -e "${GREEN}Server configured successfully.${NC}"
echo -e "${YELLOW}You can now connect simply with: ssh mlorente-$ENV${NC}"