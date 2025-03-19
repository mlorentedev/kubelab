#!/bin/bash
# check-status.sh - Check services status on server
# Usage: ./check-status.sh <environment>
# Example: ./check-status.sh production
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh" "curl"

# Check parameters
if [ "$#" -ne 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment>\nExample: $0 production"
fi

ENV=$1

# Validate environment
validate_environment "$ENV"

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

log_info "Checking status of services in $ENV environment..."

# Script to run on the server
STATUS_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

# Variables
DEPLOY_DIR="$DEPLOY_DIR"

echo "=== Server Status Report ==="
echo "Environment: $ENV"
echo "Domain: $DOMAIN"
echo "====================================="

# System information
echo -e "\n📊 System Information:"
echo "-----------------------------------"
echo "Uptime:"
uptime
echo -e "\nDisk usage:"
df -h | grep -v tmpfs
echo -e "\nMemory usage:"
free -h
echo -e "\nCPU load:"
top -bn1 | head -n 5 | tail -n 2
echo -e "\nDocker status:"
systemctl status docker --no-pager | grep Active

# Docker versions
echo -e "\n🐳 Docker Versions:"
echo "-----------------------------------"
docker --version
docker-compose --version

# Container status
echo -e "\n🔍 Container Status:"
echo "-----------------------------------"
cd "\${DEPLOY_DIR}"
docker-compose ps

# Check if all containers are running
RUNNING_CONTAINERS=\$(docker-compose ps --services --filter "status=running" | wc -l)
EXPECTED_CONTAINERS=\$(docker-compose ps --services | wc -l)

if [ "\$RUNNING_CONTAINERS" -lt "\$EXPECTED_CONTAINERS" ]; then
    echo -e "\n⚠️ Warning: Not all containers are running!"
    echo "Expected: \$EXPECTED_CONTAINERS, Running: \$RUNNING_CONTAINERS"
else
    echo -e "\n✅ All containers are running."
fi

# Container health checks
echo -e "\n🏥 Container Health Checks:"
echo "-----------------------------------"
for service in \$(docker-compose ps --services); do
    HEALTH_STATUS=\$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}N/A{{end}}' \$(docker-compose ps -q \$service) 2>/dev/null || echo "N/A")
    echo "\$service: \$HEALTH_STATUS"
done

# Resource usage
echo -e "\n📈 Resource Usage:"
echo "-----------------------------------"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# Recent logs (last 5 lines per service)
echo -e "\n📜 Recent Logs:"
echo "-----------------------------------"

echo -e "\n📘 Frontend:"
docker-compose logs --tail=5 frontend

echo -e "\n📙 Backend:"
docker-compose logs --tail=5 backend

echo -e "\n📗 Nginx:"
docker-compose logs --tail=5 nginx

# Check application access
echo -e "\n🌐 Access Check:"
echo "-----------------------------------"
curl -s -o /dev/null -w "Status code: %{http_code}\n" $SITE_URL
echo "Response time: \$(curl -s -w "%{time_total}s\n" -o /dev/null $SITE_URL)"

# Check SSL certificate
echo -e "\n🔒 SSL Certificate Check:"
echo "-----------------------------------"
SSL_EXPIRY=\$(openssl s_client -connect $DOMAIN:443 -servername $DOMAIN 2>/dev/null | openssl x509 -noout -dates 2>/dev/null)
if [ -n "\$SSL_EXPIRY" ]; then
    echo "\$SSL_EXPIRY"
else
    echo "Could not check SSL certificate."
fi

echo -e "\n=== Verification completed ==="
EOF
)

# Run script on the server
ssh "$SERVER_ALIAS" "bash -s" <<< "$STATUS_SCRIPT"

# Check application accessibility from local machine
echo -e "\n🔄 Local Connectivity Check:"
echo "-----------------------------------"
RESPONSE_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SITE_URL")
if [ "$RESPONSE_CODE" -eq 200 ]; then
    log_success "Application is accessible from your location (HTTP $RESPONSE_CODE)"
else
    log_warning "Application returned HTTP $RESPONSE_CODE from your location"
fi

# Report total check status
if [ "$RESPONSE_CODE" -eq 200 ]; then
    log_success "Status check completed successfully - all systems operational"
else
    log_warning "Status check completed with issues - some systems may need attention"
fi