#!/bin/bash
# check-status.sh - Check services status
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -ne 1 ]; then
    echo -e "${RED}Error: Missing environment.${NC}"
    echo "Usage: $0 <environment>"
    echo "Example: $0 production"
    exit 1
fi

ENV=$1

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Configure variables based on environment
if [ "$ENV" == "production" ]; then
    SERVER="mlorente-production"
    DEPLOY_DIR="/opt/mlorente"
    URL="https://mlorente.dev"
else
    SERVER="mlorente-staging"
    DEPLOY_DIR="/opt/mlorente-staging"
    URL="https://staging.mlorente.dev"
fi

# Check if we can connect to the server
if ! ssh -q $SERVER exit; then
    echo -e "${RED}Error: Cannot connect to server ${SERVER}.${NC}"
    echo "Verify that the server is correctly configured."
    exit 1
fi

echo -e "${BLUE}Checking status in ${ENV}...${NC}"

# Script to run on the server
STATUS_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="${DEPLOY_DIR}"

echo "=== Server Status ==="
echo ""

# System information
echo "📊 System Information:"
echo "-------------------------"
uptime
echo ""
df -h | grep -v tmpfs
echo ""
free -h
echo ""

# Docker versions
echo "🐳 Docker Versions:"
echo "-------------------"
docker --version
docker-compose --version
echo ""

# Container status
echo "🔍 Container Status:"
echo "--------------------------"
cd "\${DEPLOY_DIR}"
docker-compose ps
echo ""

# Recent logs (last 10 lines per service)
echo "📜 Recent Logs:"
echo "--------------"

echo "📘 Frontend:"
docker-compose logs --tail=10 frontend

echo "📙 Backend:"
docker-compose logs --tail=10 backend

echo "📗 Nginx:"
docker-compose logs --tail=10 nginx

# Check application access
echo ""
echo "🌐 Access Check:"
echo "----------------------"
curl -s -o /dev/null -w "Status code: %{http_code}\n" ${URL}
echo ""

echo "=== Verification completed ==="
EOF
)

# Run script on the server
ssh $SERVER "bash -s" <<< "$STATUS_SCRIPT"

echo -e "\n${GREEN}Verification completed.${NC}"