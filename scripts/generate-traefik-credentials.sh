#!/bin/bash
# generate-traefik-credentials.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load environment variables from .env file if it exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

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

update_env_credentials "$credentials" "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.local"

log_success "Traefik dashboard credentials generated successfully."
log_info "Username: $username"
log_info "Password: ********"
log_info "Please save these credentials securely."