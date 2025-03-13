#!/bin/bash
# analyze-logs.sh - Analyze server logs
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
    echo "Usage: $0 <environment> [service]"
    echo "Example: $0 production nginx"
    echo "Available services: frontend, backend, nginx"
    exit 1
fi

ENV=$1
SERVICE=${2:-all}

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

echo -e "${BLUE}Analyzing logs for ${ENV} (service: ${SERVICE})...${NC}"

# Script to run on the server
ANALYZE_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="${DEPLOY_DIR}"
SERVICE="${SERVICE}"

echo "=== Log Analysis ==="
echo ""

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found"
    exit 1
fi

cd "\${DEPLOY_DIR}"

# Analyze logs based on service
if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "nginx" ]; then
    echo "📊 Nginx Logs Analysis:"
    echo "----------------------"
    
    # Top 10 most visited URLs
    echo "Top 10 most visited URLs:"
    docker-compose logs nginx 2>&1 | grep -oP 'GET \K[^ ]+' | sort | uniq -c | sort -nr | head -10
    
    # Top 10 IPs
    echo -e "\nTop 10 IPs:"
    docker-compose logs nginx 2>&1 | grep -oP '\d+\.\d+\.\d+\.\d+' | sort | uniq -c | sort -nr | head -10
    
    # HTTP status codes distribution
    echo -e "\nHTTP status codes distribution:"
    docker-compose logs nginx 2>&1 | grep -oP ' HTTP/1\.[01]" \K\d+' | sort | uniq -c | sort -nr
    
    # Error log summary
    echo -e "\nError logs summary:"
    docker-compose logs nginx 2>&1 | grep -i error | wc -l | xargs -I {} echo "Total errors: {}"
    
    echo ""
fi

if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "frontend" ]; then
    echo "📊 Frontend Logs Analysis:"
    echo "------------------------"
    
    # Error log summary
    echo "Error logs summary:"
    docker-compose logs frontend 2>&1 | grep -i error | wc -l | xargs -I {} echo "Total errors: {}"
    
    # Recent errors
    echo -e "\nRecent errors (last 10):"
    docker-compose logs frontend 2>&1 | grep -i error | tail -10
    
    echo ""
fi

if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "backend" ]; then
    echo "📊 Backend Logs Analysis:"
    echo "-----------------------"
    
    # Error log summary
    echo "Error logs summary:"
    docker-compose logs backend 2>&1 | grep -i error | wc -l | xargs -I {} echo "Total errors: {}"
    
    # API endpoint usage
    echo -e "\nAPI endpoint usage:"
    docker-compose logs backend 2>&1 | grep -oP 'GET|POST|PUT|DELETE \K[^ ]+' | sort | uniq -c | sort -nr | head -10
    
    # Recent errors
    echo -e "\nRecent errors (last 10):"
    docker-compose logs backend 2>&1 | grep -i error | tail -10
    
    echo ""
fi

echo "=== Log analysis completed ==="
EOF
)

# Run log analysis script on the server
ssh $SERVER "bash -s" <<< "$ANALYZE_SCRIPT"

echo -e "${GREEN}Log analysis completed.${NC}"