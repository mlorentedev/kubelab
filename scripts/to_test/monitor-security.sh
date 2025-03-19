#!/bin/bash
# security-check.sh - Check server security configuration
# Usage: ./security-check.sh <environment>
# Example: ./security-check.sh production
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh" "curl" "openssl"

# Check parameters
if [ "$#" -ne 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment>\nExample: $0 production"
fi

ENV=$1

# Validate environment
validate_environment "$ENV"

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

log_info "Running security checks for $ENV environment..."

# Create the report filename
REPORT_FILE="${ENV}_security_check_$(date +%Y%m%d%H%M%S).txt"

# Script to run on the server
SECURITY_SCRIPT=$(cat <<EOF
#!/bin/bash
set -e

echo "=== Security Check Report ==="
echo "Environment: $ENV"
echo "Server: $SERVER_HOST"
echo "Date: $(date)"
echo "====================================="

# Check for outdated packages
echo -e "\n📦 Outdated Packages:"
echo "-----------------------------------"
apt list --upgradable 2>/dev/null | grep -v "Listing..." | wc -l | xargs -I {} echo "Outdated packages: {}"

# Show some critical outdated packages if any
echo "Critical outdated packages (kernel, openssl, ssh, sudo):"
apt list --upgradable 2>/dev/null | grep -E "linux-|openssl|openssh|sudo" || echo "None found"

# Check if security updates are enabled
echo -e "\n🔄 Automatic Updates:"
echo "-----------------------------------"
if dpkg -l | grep -q unattended-upgrades; then
    echo "✅ unattended-upgrades is installed"
    if grep -q "Unattended-Upgrade::Allowed-Origins" /etc/apt/apt.conf.d/50unattended-upgrades; then
        echo "✅ Security updates are configured"
    else
        echo "❌ Security updates may not be properly configured"
    fi
else
    echo "❌ unattended-upgrades is not installed"
fi

# Check firewall status
echo -e "\n🔥 Firewall Status:"
echo "-----------------------------------"
if command -v ufw &> /dev/null; then
    if ufw status | grep -q "Status: active"; then
        echo "✅ Firewall (ufw) is active"
        ufw status | grep -v "Status:"
    else
        echo "❌ Firewall (ufw) is not active"
    fi
else
    echo "❌ ufw is not installed"
fi

# Check SSH configuration
echo -e "\n🔑 SSH Configuration:"
echo "-----------------------------------"
SSH_CONFIG="/etc/ssh/sshd_config"

# Check PasswordAuthentication
if grep -q "^PasswordAuthentication no" \$SSH_CONFIG; then
    echo "✅ SSH password authentication is disabled"
else
    echo "❌ SSH password authentication is enabled or not explicitly set"
fi

# Check PermitRootLogin
if grep -q "^PermitRootLogin no" \$SSH_CONFIG; then
    echo "✅ SSH root login is disabled"
elif grep -q "^PermitRootLogin prohibit-password" \$SSH_CONFIG; then
    echo "⚠️ SSH root login is allowed with key authentication only"
else
    echo "❌ SSH root login may be allowed with password"
fi

# Check for other important SSH settings
echo "Other SSH security settings:"

# Protocol version
if grep -q "^Protocol 2" \$SSH_CONFIG; then
    echo "✅ SSH Protocol 2 enforced"
else
    echo "⚠️ SSH Protocol version not explicitly set to 2"
fi

# Maximum authentication attempts
MAX_AUTH=\$(grep "^MaxAuthTries" \$SSH_CONFIG | awk '{print \$2}')
if [ -n "\$MAX_AUTH" ] && [ "\$MAX_AUTH" -le 6 ]; then
    echo "✅ MaxAuthTries is set to \$MAX_AUTH"
else
    echo "⚠️ MaxAuthTries not set or too high"
fi

# X11 forwarding
if grep -q "^X11Forwarding no" \$SSH_CONFIG; then
    echo "✅ X11 forwarding is disabled"
else
    echo "⚠️ X11 forwarding may be enabled"
fi

# Check fail2ban status
echo -e "\n🛡️ Fail2ban Status:"
echo "-----------------------------------"
if command -v fail2ban-client &> /dev/null; then
    if systemctl is-active --quiet fail2ban; then
        echo "✅ Fail2ban is active"
        echo "Active jails:"
        fail2ban-client status | grep "Jail list" | sed 's/^[^:]*:[ \t]*//'
    else
        echo "❌ Fail2ban is installed but not active"
    fi
else
    echo "❌ Fail2ban is not installed"
fi

# Check for Docker security issues
echo -e "\n🐳 Docker Security:"
echo "-----------------------------------"
if command -v docker &> /dev/null; then
    echo "✅ Docker is installed"
    
    # Check Docker Bench Security (if available)
    if command -v docker-bench-security &> /dev/null; then
        echo "Running Docker Bench Security (summary)..."
        docker-bench-security --check-c 1,2,3 | grep "\[WARN\]"
    else
        echo "⚠️ docker-bench-security not available, skipping detailed checks"
    fi
    
    # Basic Docker security checks
    echo "Basic Docker security checks:"
    
    # Check for containers running as root
    ROOT_CONTAINERS=\$(docker ps --quiet | xargs docker inspect --format '{{ .Id }}: User={{ .Config.User }}' | grep -c "User=$")
    if [ "\$ROOT_CONTAINERS" -gt 0 ]; then
        echo "❌ \$ROOT_CONTAINERS containers running as root"
    else
        echo "✅ No containers running as root"
    fi
    
    # Check for exposed ports
    EXPOSED_PORTS=\$(docker ps --format "{{.Ports}}" | grep -c "0.0.0.0")
    if [ "\$EXPOSED_PORTS" -gt 2 ]; then  # Allow 80 and 443
        echo "⚠️ \$EXPOSED_PORTS ports exposed to all interfaces"
    else
        echo "✅ Minimal port exposure"
    fi
else
    echo "Docker not installed, skipping Docker security checks"
fi

# Check TLS certificates
echo -e "\n🔒 TLS Certificates:"
echo "-----------------------------------"
if [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    CERT_EXPIRY=\$(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/${DOMAIN}/cert.pem")
    echo "✅ Certificate found: \${CERT_EXPIRY}"
    
    # Check certificate key strength
    KEY_STRENGTH=\$(openssl x509 -in "/etc/letsencrypt/live/${DOMAIN}/cert.pem" -noout -text | grep "Public-Key:" | grep -o "[0-9]\+ bit")
    echo "Certificate key strength: \$KEY_STRENGTH"
    
    # Check certificate signature algorithm
    SIG_ALG=\$(openssl x509 -in "/etc/letsencrypt/live/${DOMAIN}/cert.pem" -noout -text | grep "Signature Algorithm" | head -1 | sed 's/.*Signature Algorithm: //')
    echo "Signature algorithm: \$SIG_ALG"
else
    echo "❌ No certificate found for ${DOMAIN}"
fi

# Check for certbot automatic renewal
if command -v certbot &> /dev/null; then
    echo "Certbot renewal status:"
    systemctl list-timers | grep certbot || echo "No certbot timer found"
fi

# Check for open ports
echo -e "\n🔌 Open Ports:"
echo "-----------------------------------"
if command -v netstat &> /dev/null; then
    LISTENING_PORTS=\$(netstat -tuln | grep LISTEN)
    if [ -n "\$LISTENING_PORTS" ]; then
        echo "TCP/UDP ports listening on all interfaces (0.0.0.0):"
        netstat -tuln | grep "0.0.0.0" | sort -t: -k2 -n
    else
        echo "No open TCP/UDP ports found"
    fi
else
    echo "netstat not available, using ss instead"
    ss -tuln | grep LISTEN | sort -t: -k2 -n
fi

# Check user accounts with shell access
echo -e "\n👤 User Accounts with Shell Access:"
echo "-----------------------------------"
grep -v "/usr/sbin/nologin\|/bin/false" /etc/passwd | cut -d: -f1,7 | sort
SUDOERS=\$(grep -l "" /etc/sudoers.d/* 2>/dev/null | xargs cat 2>/dev/null | grep -v "^#" | grep "ALL=" | sort)
echo -e "\nUsers with sudo access:"
if [ -n "\$SUDOERS" ]; then
    echo "\$SUDOERS"
else
    echo "None found in /etc/sudoers.d/"
    grep -v "^#" /etc/sudoers | grep "ALL=" || echo "None found in main sudoers file"
fi

# Check for suspicious processes
echo -e "\n🔍 Suspicious Processes:"
echo "-----------------------------------"
echo "Processes running as root with open network connections:"
ps aux | grep ^root | grep -v "\[" | sort -nrk 3,3 | head -10
echo -e "\nProcesses using high CPU:"
ps aux | sort -nrk 3,3 | head -5

echo "=== Security check completed ==="
EOF
)

# Run security script on the server and save to report
ssh "$SERVER_ALIAS" "bash -s" <<< "$SECURITY_SCRIPT" | tee "$REPORT_FILE"

# Run external security checks
log_info "Running external security checks..."

# SSL check
echo -e "\n🔒 External SSL Certificate Check:" | tee -a "$REPORT_FILE"
echo "-----------------------------------" | tee -a "$REPORT_FILE"
if ! openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN} 2>/dev/null | openssl x509 -noout -dates | tee -a "$REPORT_FILE"; then
    echo "❌ Could not connect to ${DOMAIN}:443" | tee -a "$REPORT_FILE"
fi

# HTTP security headers
echo -e "\n🛡️ HTTP Security Headers:" | tee -a "$REPORT_FILE"
echo "-----------------------------------" | tee -a "$REPORT_FILE"
if curl -s -I "https://${DOMAIN}" | grep -E "^(Strict-Transport-Security|Content-Security-Policy|X-Content-Type-Options|X-Frame-Options|Referrer-Policy|Permissions-Policy)" | tee -a "$REPORT_FILE"; then
    echo "Found security headers" | tee -a "$REPORT_FILE"
else
    echo "❌ No recommended security headers found" | tee -a "$REPORT_FILE"
fi

# Check for missing security headers
echo -e "\nMissing recommended security headers:" | tee -a "$REPORT_FILE"
for header in "Strict-Transport-Security" "Content-Security-Policy" "X-Content-Type-Options" "X-Frame-Options" "Referrer-Policy" "Permissions-Policy"; do
    if ! curl -s -I "https://${DOMAIN}" | grep -q "^$header"; then
        echo "❌ Missing: $header" | tee -a "$REPORT_FILE"
    fi
done

# TLS version and cipher check
echo -e "\n🔐 TLS Configuration:" | tee -a "$REPORT_FILE"
echo "-----------------------------------" | tee -a "$REPORT_FILE"
echo "Supported TLS versions:" | tee -a "$REPORT_FILE"
for version in "tls1" "tls1_1" "tls1_2" "tls1_3"; do
    if openssl s_client -connect ${DOMAIN}:443 -servername ${DOMAIN} -$version 2>/dev/null | grep -q "CONNECTED"; then
        if [ "$version" == "tls1" ] || [ "$version" == "tls1_1" ]; then
            echo "❌ Supports legacy $version (insecure)" | tee -a "$REPORT_FILE"
        else
            echo "✅ Supports $version" | tee -a "$REPORT_FILE"
        fi
    else
        if [ "$version" == "tls1" ] || [ "$version" == "tls1_1" ]; then
            echo "✅ Does not support legacy $version" | tee -a "$REPORT_FILE"
        else
            echo "❌ Does not support $version" | tee -a "$REPORT_FILE"
        fi
    fi
done

log_success "Security checks completed. Report saved to $REPORT_FILE"

# Ask if user wants to open the report
if command -v less &> /dev/null; then
    if confirm_action "Do you want to view the full report now?"; then
        less "$REPORT_FILE"
    fi
fi