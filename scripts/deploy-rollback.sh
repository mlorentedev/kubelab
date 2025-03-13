#!/bin/bash
# rollback.sh - Rollback to a previous version
# Usage: ./rollback.sh <environment> [version]
# Example: ./rollback.sh production v1.2.2
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh"

# Check parameters
if [ "$#" -lt 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment> [version]\nExample: $0 production v1.2.2"
fi

ENV=$1
VERSION=${2:-""}

# Validate environment
validate_environment "$ENV"

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

# If no version specified, list available versions
if [ -z "$VERSION" ]; then
    log_info "Querying available versions on $ENV server..."
    
    FRONTEND_VERSIONS=$(ssh "$SERVER_ALIAS" "docker images --format '{{.Repository}}:{{.Tag}}' | grep mlorente-frontend | sort -V")
    BACKEND_VERSIONS=$(ssh "$SERVER_ALIAS" "docker images --format '{{.Repository}}:{{.Tag}}' | grep mlorente-backend | sort -V")
    
    echo -e "${YELLOW}Available frontend versions:${NC}"
    echo "$FRONTEND_VERSIONS"
    
    echo -e "\n${YELLOW}Available backend versions:${NC}"
    echo "$BACKEND_VERSIONS"
    
    echo -e "\n${YELLOW}Enter the version to rollback to:${NC}"
    read VERSION
    
    if [ -z "$VERSION" ]; then
        exit_error "No version specified. Rollback cancelled."
    fi
fi

log_info "Preparing to rollback $ENV to version $VERSION..."

# Confirm rollback
if ! confirm_action "⚠️ WARNING: This will rollback $ENV to version $VERSION. This action cannot be easily undone.\nAre you sure you want to continue?"; then
    log_warning "Rollback cancelled."
    exit 0
fi

# Get timestamp for backup
TIMESTAMP=$(get_timestamp)

# Rollback script to run on the server
ROLLBACK_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="$DEPLOY_DIR"
VERSION="$VERSION"
TIMESTAMP="$TIMESTAMP"
BACKUP_DIR="\${DEPLOY_DIR}/backups/rollback_\${TIMESTAMP}"

echo "=== Starting rollback to version \${VERSION} ==="

# Create backup directory
mkdir -p "\${BACKUP_DIR}"

# Backup current configuration
echo "Backing up current configuration..."
cp "\${DEPLOY_DIR}/.env" "\${BACKUP_DIR}/.env.backup"
cp "\${DEPLOY_DIR}/docker-compose.yml" "\${BACKUP_DIR}/docker-compose.yml.backup"

# Check if the specified version images exist
echo "Checking image availability..."
FRONTEND_EXISTS=\$(docker images | grep mlorente-frontend | grep "\${VERSION}" | wc -l)
BACKEND_EXISTS=\$(docker images | grep mlorente-backend | grep "\${VERSION}" | wc -l)

if [ "\$FRONTEND_EXISTS" -eq 0 ] || [ "\$BACKEND_EXISTS" -eq 0 ]; then
    echo "Error: Images not found for version \${VERSION}"
    echo "Frontend available: \$FRONTEND_EXISTS, Backend available: \$BACKEND_EXISTS"
    exit 1
fi

# Save current container IDs for later comparison
CURRENT_CONTAINER_IDS=\$(docker-compose ps -q)

# Set version in environment variables
echo "Configuring version: \${VERSION}"
export TAG=\${VERSION}

# Stop current services before deploying previous version
echo "Stopping current services..."
docker-compose down

# Deploy previous version
echo "Deploying version \${VERSION}..."
docker-compose up -d

# Verify rollback
echo "Verifying rollback..."
sleep 10

# Get new container IDs
NEW_CONTAINER_IDS=\$(docker-compose ps -q)

# Check if all containers are running
ALL_RUNNING=true
for container in \$NEW_CONTAINER_IDS; do
    if ! docker inspect --format='{{.State.Running}}' \$container | grep -q "true"; then
        ALL_RUNNING=false
        break
    fi
done

if [ "\$ALL_RUNNING" = false ]; then
    echo "Warning: Not all containers are running after rollback."
    echo "Container status:"
    docker-compose ps
    echo "You may need to check logs with: docker-compose logs"
    exit 1
fi

echo "All containers are running after rollback."
echo "=== Rollback completed successfully ==="
EOF
)

# Run rollback script on the server
log_info "Connecting to server $SERVER_ALIAS and executing rollback..."
if ssh "$SERVER_ALIAS" "bash -s" <<< "$ROLLBACK_SCRIPT"; then
    log_success "Rollback to version $VERSION completed successfully!"
    log_info "You can verify the application status with: ./check-status.sh $ENV"
else
    log_error "Rollback failed. Please check the logs on the server."
    log_info "You can check the status with: ./check-status.sh $ENV"
    exit 1
fi