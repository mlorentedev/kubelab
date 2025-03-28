#!/bin/bash
# generate-traefik-credentials.sh

# Get the directory of the script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Source utility functions
source "$PROJECT_DIR/scripts/utils.sh"

# Function to generate basic auth credentials
generate_basic_auth() {
  local username=$1
  local password=$2
  
  # Generate password hash
  if command -v htpasswd > /dev/null; then
    local hashed_password=$(htpasswd -nb "$username" "$password")
    echo "$hashed_password"
  else
    # Fallback to using openssl if htpasswd is not available
    local hashed_password=$(openssl passwd -apr1 "$password")
    echo "${username}:${hashed_password}"
  fi
}

# Request username
read -p "Enter username for Traefik dashboard (default: admin): " username
username=${username:-admin}

# Request password with confirmation
read -s -p "Enter password: " password
echo
if [ -z "$password" ]; then
  log_error "Password cannot be empty"
  exit 1
fi

# Confirm password
read -s -p "Confirm password: " password_confirm
echo
if [ "$password" != "$password_confirm" ]; then
  log_error "Passwords do not match"
  exit 1
fi

# Generate the credentials
credentials=$(generate_basic_auth "$username" "$password")

# Add to .env files
for env_file in .env.staging .env.production; do
  if [ -f "$env_file" ]; then
    # Remove existing TRAEFIK_DASHBOARD_USERS line if it exists
    sed -i '/TRAEFIK_DASHBOARD_USERS=/d' "$env_file"
    # Add the new credentials
    echo "TRAEFIK_DASHBOARD_USERS=$credentials" >> "$env_file"
    log_success "Added credentials to $env_file"
  else
    log_warning "File $env_file doesn't exist, skipping."
  fi
done

log_success "Traefik dashboard credentials generated successfully."
log_info "Username: $username"
log_info "Password: ********"
log_info "Please save these credentials securely."
log_info "To apply changes, restart Traefik with:"
log_info "  ./scripts/deploy-multi.sh stop common"
log_info "  ./scripts/deploy-multi.sh deploy common"