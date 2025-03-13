#!/bin/bash
# deploy.sh - Script to deploy the application
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -lt 1 ]; then
    echo -e "${RED}Error: Missing deployment environment.${NC}"
    echo "Usage: $0 <environment> [version]"
    echo "Example: $0 production latest"
    echo "Example: $0 staging v1.2.3"
    exit 1
fi

ENV=$1
VERSION=${2:-latest}

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Configure variables based on environment
if [ "$ENV" == "production" ]; then
    SERVER="mlorente-production"
    DEPLOY_DIR="/opt/mlorente"
    BRANCH="master"
else
    SERVER="mlorente-staging"
    DEPLOY_DIR="/opt/mlorente-staging"
    BRANCH="develop"
fi

echo -e "${BLUE}Deploying version ${VERSION} to ${ENV}...${NC}"

# Check if we can connect to the server
if ! ssh -q $SERVER exit; then
    echo -e "${RED}Error: Cannot connect to server ${SERVER}.${NC}"
    echo "Verify that the server is correctly configured."
    exit 1
fi

# Deployment script to run on the server
DEPLOY_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="${DEPLOY_DIR}"
BRANCH="${BRANCH}"
VERSION="${VERSION}"
TIMESTAMP=\$(date +%Y%m%d%H%M%S)
BACKUP_DIR="\${DEPLOY_DIR}/backups/\${TIMESTAMP}"

echo "=== Starting deployment to \${DEPLOY_DIR} ==="
echo "Branch: \${BRANCH}, Version: \${VERSION}, Timestamp: \${TIMESTAMP}"

# Create backup directory
mkdir -p "\${BACKUP_DIR}"

# Backup current configuration
if [ -f "\${DEPLOY_DIR}/.env" ]; then
    echo "Backing up configuration files..."
    cp "\${DEPLOY_DIR}/.env" "\${BACKUP_DIR}/.env.backup"
    cp "\${DEPLOY_DIR}/docker-compose.yml" "\${BACKUP_DIR}/docker-compose.yml.backup" 2>/dev/null || true
fi

# Update repository
echo "Updating repository..."
if [ -d "\${DEPLOY_DIR}/repo" ]; then
    cd "\${DEPLOY_DIR}/repo"
    git fetch --all
    git checkout \${BRANCH}
    git pull origin \${BRANCH}
else
    echo "Cloning repository..."
    mkdir -p "\${DEPLOY_DIR}/repo"
    git clone -b \${BRANCH} https://github.com/mlorentedev/mlorente.dev.git "\${DEPLOY_DIR}/repo"
    cd "\${DEPLOY_DIR}/repo"
fi

# Copy updated docker-compose.yml
echo "Updating docker-compose.yml..."
cp "\${DEPLOY_DIR}/repo/docker-compose.yml" "\${DEPLOY_DIR}/"

# Set version in environment variables
echo "Configuring version: \${VERSION}"
export TAG=\${VERSION}

# Deploy services
echo "Deploying services..."
cd "\${DEPLOY_DIR}"
docker-compose pull
docker-compose up -d

# Clean old images
echo "Cleaning old images..."
docker image prune -af --filter "until=24h"

echo "=== Deployment completed successfully ==="
EOF
)

# Run deployment script on the server
echo -e "${BLUE}Connecting to server ${SERVER}...${NC}"
ssh $SERVER "bash -s" <<< "$DEPLOY_SCRIPT"

echo -e "${GREEN}Deployment completed successfully.${NC}"
echo -e "${YELLOW}The application is available at: https://$([ "$ENV" == "production" ] && echo "mlorente.dev" || echo "staging.mlorente.dev")${NC}"