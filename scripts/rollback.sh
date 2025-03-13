#!/bin/bash
# rollback.sh - Rollback to a previous version
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -lt 1 ]; then
    echo -e "${RED}Error: Missing environment.${NC}"
    echo "Usage: $0 <environment> [version]"
    echo "Example: $0 production v1.2.2"
    exit 1
fi

ENV=$1
VERSION=${2:-""}

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Configure variables based on environment
if [ "$ENV" == "production" ]; then
    SERVER="mlorente-production"
    DEPLOY_DIR="/opt/mlorente"
else
    SERVER="mlorente-staging"
    DEPLOY_DIR="/opt/mlorente-staging"
fi

# Check if we can connect to the server
if ! ssh -q $SERVER exit; then
    echo -e "${RED}Error: Cannot connect to server ${SERVER}.${NC}"
    echo "Verify that the server is correctly configured."
    exit 1
fi

# If no version specified, list available versions
if [ -z "$VERSION" ]; then
    echo -e "${BLUE}Querying available versions...${NC}"
    echo -e "${YELLOW}Available frontend versions:${NC}"
    ssh $SERVER "docker images | grep mlorente-frontend | awk '{print \$2}'"
    echo -e "${YELLOW}Available backend versions:${NC}"
    ssh $SERVER "docker images | grep mlorente-backend | awk '{print \$2}'"
    
    echo -e "\n${YELLOW}Enter the version to rollback to:${NC}"
    read VERSION
    
    if [ -z "$VERSION" ]; then
        echo -e "${RED}Error: No valid version specified.${NC}"
        exit 1
    fi
fi

echo -e "${BLUE}Rolling back to version ${VERSION} in ${ENV}...${NC}"

# Rollback script to run on the server
ROLLBACK_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="${DEPLOY_DIR}"
VERSION="${VERSION}"
TIMESTAMP=\$(date +%Y%m%d%H%M%S)
BACKUP_DIR="\${DEPLOY_DIR}/backups/rollback_\${TIMESTAMP}"

echo "=== Starting rollback to version \${VERSION} ==="

# Create backup directory
mkdir -p "\${BACKUP_DIR}"

# Backup current configuration
echo "Backing up current configuration..."
cp "\${DEPLOY_DIR}/.env" "\${BACKUP_DIR}/.env.backup"
cp "\${DEPLOY_DIR}/docker-compose.yml" "\${BACKUP_DIR}/docker-compose.yml.backup"

# Check if version images exist
echo "Checking image availability..."
FRONTEND_EXISTS=\$(docker images | grep mlorente-frontend | grep "\${VERSION}" | wc -l)
BACKEND_EXISTS=\$(docker images | grep mlorente-backend | grep "\${VERSION}" | wc -l)

if [ "\$FRONTEND_EXISTS" -eq 0 ] || [ "\$BACKEND_EXISTS" -eq 0 ]; then
    echo "Error: Images not found for version \${VERSION}"
    echo "Frontend available: \$FRONTEND_EXISTS, Backend available: \$BACKEND_EXISTS"
    exit 1
fi

# Set version in environment variables
echo "Configuring version: \${VERSION}"
export TAG=\${VERSION}

# Deploy previous version
echo "Deploying version \${VERSION}..."
cd "\${DEPLOY_DIR}"
docker-compose up -d

echo "=== Rollback completed successfully ==="
EOF
)

# Run rollback script on the server
echo -e "${BLUE}Connecting to server ${SERVER}...${NC}"
ssh $SERVER "bash -s" <<< "$ROLLBACK_SCRIPT"

echo -e "${GREEN}Rollback completed successfully.${NC}"
echo -e "${YELLOW}The application has been rolled back to version ${VERSION}.${NC}"