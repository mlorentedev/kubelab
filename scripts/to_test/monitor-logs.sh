#!/bin/bash
# analyze-logs.sh - Analyze server logs
# Usage: ./analyze-logs.sh <environment> [service]
# Example: ./analyze-logs.sh production nginx
# Available services: frontend, backend, nginx, all (default)
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh"

# Check parameters
if [ "$#" -lt 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment> [service]\nExample: $0 production nginx\nAvailable services: frontend, backend, nginx, all (default)"
fi

ENV=$1
SERVICE=${2:-all}

# Validate environment
validate_environment "$ENV"

# Validate service
if [[ "$SERVICE" != "all" && "$SERVICE" != "frontend" && "$SERVICE" != "backend" && "$SERVICE" != "nginx" ]]; then
    exit_error "Invalid service: $SERVICE\nAvailable services: frontend, backend, nginx, all"
fi

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

log_info "Analyzing logs for $ENV environment (service: $SERVICE)"

# Script to run on the server
ANALYZE_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="$DEPLOY_DIR"
SERVICE="$SERVICE"

echo "=== Log Analysis Report ==="
echo "Environment: $ENV"
echo "Service: $SERVICE"
echo "Date: $(date)"
echo "====================================="

# Check if Docker Compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found"
    exit 1
fi

cd "\${DEPLOY_DIR}"

# Create temporary directory for log extraction
mkdir -p ./tmp/logs
TEMP_DIR="./tmp/logs"

# Function to get logs for a service
extract_logs() {
    local service=\$1
    echo "Extracting logs for \$service..."
    docker-compose logs \$service > "\${TEMP_DIR}/\${service}.log" 2>&1
}

# Extract logs for requested services
if [ "\${SERVICE}" == "all" ]; then
    echo "Extracting logs for all services..."
    extract_logs "nginx"
    extract_logs "frontend"
    extract_logs "backend"
else
    extract_logs "\${SERVICE}"
fi

# Analyze logs based on service
if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "nginx" ]; then
    echo ""
    echo "📊 Nginx Logs Analysis:"
    echo "======================="
    
    # Get Nginx log file
    NGINX_LOG="\${TEMP_DIR}/nginx.log"
    
    # Top 10 most visited URLs
    echo "Top 10 most visited URLs:"
    grep -oP 'GET \K[^ ]+' "\${NGINX_LOG}" | sort | uniq -c | sort -nr | head -10 || echo "No URLs found"
    
    # Top 10 IPs
    echo -e "\nTop 10 client IPs:"
    grep -oP '\d+\.\d+\.\d+\.\d+' "\${NGINX_LOG}" | sort | uniq -c | sort -nr | head -10 || echo "No IPs found"
    
    # HTTP status codes distribution
    echo -e "\nHTTP status codes distribution:"
    grep -oP ' HTTP/1\.[01]" \K\d+' "\${NGINX_LOG}" | sort | uniq -c | sort -nr || echo "No status codes found"
    
    # 4xx/5xx errors
    echo -e "\nError status codes (4xx/5xx):"
    grep -oP ' HTTP/1\.[01]" \K[45]\d\d' "\${NGINX_LOG}" | sort | uniq -c | sort -nr || echo "No error codes found"
    
    # Error log summary
    echo -e "\nError logs summary:"
    grep -i error "\${NGINX_LOG}" | wc -l | xargs -I {} echo "Total errors: {}"
    
    # Show sample of recent errors
    echo -e "\nRecent errors (last 5):"
    grep -i error "\${NGINX_LOG}" | tail -5 || echo "No recent errors"
fi

if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "frontend" ]; then
    echo ""
    echo "📊 Frontend Logs Analysis:"
    echo "========================="
    
    # Get Frontend log file
    FRONTEND_LOG="\${TEMP_DIR}/frontend.log"
    
    # Error log summary
    echo "Error logs summary:"
    grep -i error "\${FRONTEND_LOG}" | wc -l | xargs -I {} echo "Total errors: {}"
    
    # Warning log summary
    echo -e "\nWarning logs summary:"
    grep -i warn "\${FRONTEND_LOG}" | wc -l | xargs -I {} echo "Total warnings: {}"
    
    # Recent errors
    echo -e "\nRecent errors (last 5):"
    grep -i error "\${FRONTEND_LOG}" | tail -5 || echo "No recent errors"
    
    # Common error patterns
    echo -e "\nCommon error patterns:"
    grep -i error "\${FRONTEND_LOG}" | awk '{$1=""; $2=""; $3=""; print $0}' | sort | uniq -c | sort -nr | head -5 || echo "No error patterns found"
fi

if [ "\${SERVICE}" == "all" ] || [ "\${SERVICE}" == "backend" ]; then
    echo ""
    echo "📊 Backend Logs Analysis:"
    echo "========================"
    
    # Get Backend log file
    BACKEND_LOG="\${TEMP_DIR}/backend.log"
    
    # Error log summary
    echo "Error logs summary:"
    grep -i error "\${BACKEND_LOG}" | wc -l | xargs -I {} echo "Total errors: {}"
    
    # API endpoint usage
    echo -e "\nAPI endpoint usage:"
    grep -oP 'GET|POST|PUT|DELETE \K[^ ]+' "\${BACKEND_LOG}" | sort | uniq -c | sort -nr | head -10 || echo "No API endpoints found"
    
    # Recent errors
    echo -e "\nRecent errors (last 5):"
    grep -i error "\${BACKEND_LOG}" | tail -5 || echo "No recent errors"
    
    # Common error patterns
    echo -e "\nCommon error patterns:"
    grep -i error "\${BACKEND_LOG}" | awk '{$1=""; $2=""; $3=""; print $0}' | sort | uniq -c | sort -nr | head -5 || echo "No error patterns found"
    
    # Response time analysis (if available)
    echo -e "\nResponse time summary:"
    grep -i "time=" "\${BACKEND_LOG}" | grep -oP 'time=\K[0-9.]+' | awk '{ sum += \$1; count++ } END { if (count > 0) print "Average response time:", sum/count, "ms,", "Count:", count; else print "No response time data available" }' || echo "No response time data found"
fi

# Clean up temporary files
rm -rf "\${TEMP_DIR}"

echo "=== Log analysis completed ==="
EOF
)

# Run log analysis script on the server
ssh "$SERVER_ALIAS" "bash -s" <<< "$ANALYZE_SCRIPT" | tee "${ENV}_${SERVICE}_logs_$(date +%Y%m%d%H%M%S).txt"

log_success "Log analysis completed. Results saved to ${ENV}_${SERVICE}_logs_$(date +%Y%m%d%H%M%S).txt"