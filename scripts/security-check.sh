#!/bin/bash
# security-check.sh - Check server security
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
    DOMAIN="mlorente.dev"
else
    SERVER="mlorente-staging"
    DOMAIN="staging.mlorente.dev"
fi

# Check if we can connect to the server
if ! ssh -q $SERVER exit; then
    echo -e "${RED}Error: Cannot connect to server ${SERVER}.${NC}"
    echo "Verify that the server is correctly configured."
    exit 1
fi

echo -e "${BLUE}Running security checks for ${ENV}...${NC}"

# Script to run on the server
SECURITY_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

echo "=== Security Check Report ==="
echo ""

# Check for outdated packages
echo "📦 Checking for outdated packages..."
apt list --upgradable 2>/dev/null | grep -v "Listing..." | wc -l | xargs -I {} echo "Outdated packages: {}"
echo ""

# Check if firewall is enabled
echo "🔥 Checking firewall status..."
if ufw status | grep -q "Status: active"; then
    echo "✅ Firewall is active"
    ufw status
else
    echo "❌ Firewall is not active"
fi
echo ""

# Check SSH configuration
echo "🔑 Checking SSH configuration..."
if grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config; then
    echo "✅ SSH password authentication is disabled"
else
    echo "❌ SSH password authentication is enabled"
fi

if grep -q "^PermitRootLogin no" /etc/ssh/sshd_config; then
    echo "✅ SSH root login is disabled"
else
    echo "❌ SSH root login is allowed"
fi
echo ""

# Check fail2ban status
echo "🛡️ Checking fail2ban status..."
if systemctl is-active --quiet fail2ban; then
    echo "✅ Fail2ban is active"
    fail2ban-client status | grep "Jail list"
else
    echo "❌ Fail2ban is not active"
fi
echo ""

# Check Docker security
echo "🐳 Checking Docker security..."
echo "Running containers:"
docker ps --format "table {{.ID}}\t{{.Image}}\t{{.Status}}"
echo ""
echo "Container security scanning would normally be run here"
echo ""

# Check TLS certificates
echo "🔒 Checking TLS certificates..."
if [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    CERT_EXPIRY=\$(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/${DOMAIN}/cert.pem")
    echo "✅ Certificate found: \${CERT_EXPIRY}"
else
    echo "❌ No certificate found for ${DOMAIN}"
fi
echo ""

# Check for open ports
echo "🔌 Checking open ports..."
netstat -tulpn | grep LISTEN
echo ""

echo "=== Security check completed ==="
EOF
)

# Run security script on the server
ssh $SERVER "bash -s" <<< "$SECURITY_SCRIPT"

# Run SSL check locally
echo -e "\n${BLUE}Checking SSL certificate from outside...${NC}"
if command -v openssl &> /dev/null; then
    openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN} 2>/dev/null | openssl x509 -noout -dates
else
    echo -e "${YELLOW}OpenSSL not found. Skipping external SSL check.${NC}"
fi

echo -e "\n${BLUE}Checking HTTP security headers...${NC}"
if command -v curl &> /dev/null; then
    curl -s -I https://${DOMAIN} | grep -E "^(Strict-Transport-Security|Content-Security-Policy|X-Content-Type-Options|X-Frame-Options|Referrer-Policy|Permissions-Policy)"
else
    echo -e "${YELLOW}curl not found. Skipping HTTP header check.${NC}"
fi

echo -e "\n${GREEN}Security checks completed.${NC}"