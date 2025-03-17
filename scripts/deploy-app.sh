#!/bin/bash
# deploy.sh - Deploy mlorente.dev application to server
# Usage: ./deploy.sh <environment> [version]
# Example: ./deploy.sh production latest
# Example: ./deploy.sh staging v1.2.3
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh" "git"

# Check parameters
if [ "$#" -lt 1 ]; then
    exit_error "Missing deployment environment.\nUsage: $0 <environment> [version]\nExample: $0 production latest"
fi

ENV=$1
VERSION=${2:-latest}

# Validate environment
validate_environment "$ENV"

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

log_info "Deploying version $VERSION to $ENV environment..."

# Get the current timestamp for backups
TIMESTAMP=$(get_timestamp)

# Confirm deployment
if ! confirm_action "This will deploy version $VERSION to $ENV. Continue?"; then
    exit 0
fi

# Deployment script to run on the server
DEPLOY_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="$DEPLOY_DIR"
BRANCH="$BRANCH"
VERSION="$VERSION"
TIMESTAMP="$TIMESTAMP"
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
    # Force reset only if we're using the latest from a branch
    if [ "\${VERSION}" == "latest" ]; then
        git reset --hard origin/\${BRANCH}
        git pull origin \${BRANCH}
    else
        # If specific version tag, checkout that
        if git tag | grep -q "^\${VERSION}\$"; then
            git checkout \${VERSION}
        else
            echo "Warning: Version \${VERSION} not found in tags, using latest from \${BRANCH}"
            git reset --hard origin/\${BRANCH}
            git pull origin \${BRANCH}
        fi
    fi
else
    echo "Cloning repository..."
    mkdir -p "\${DEPLOY_DIR}/repo"
    git clone -b \${BRANCH} https://github.com/mlorentedev/mlorente.dev.git "\${DEPLOY_DIR}/repo"
    cd "\${DEPLOY_DIR}/repo"
    
    # If specific version tag, checkout that
    if [ "\${VERSION}" != "latest" ]; then
        if git tag | grep -q "^\${VERSION}\$"; then
            git checkout \${VERSION}
        else
            echo "Warning: Version \${VERSION} not found in tags, using latest from \${BRANCH}"
        fi
    fi
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

# Verify deployment
sleep 5
if ! docker-compose ps | grep -q "Up"; then
    echo "Error: Deployment verification failed. Some containers are not running."
    echo "Check logs with: docker-compose logs"
    exit 1
fi

# Clean old images
echo "Cleaning old images..."
docker image prune -af --filter "until=24h" || true

echo "=== Deployment completed successfully ==="
echo "Check application status with: docker-compose ps"
echo "View logs with: docker-compose logs"
EOF
)

# Run deployment script on the server
log_info "Connecting to server $SERVER_ALIAS and running deployment..."
ssh "$SERVER_ALIAS" "bash -s" <<< "$DEPLOY_SCRIPT"

log_success "Deployment completed successfully."
log_info "The application is available at: $SITE_URL"
log_info "Check the status with: ./check-status.sh $ENV"