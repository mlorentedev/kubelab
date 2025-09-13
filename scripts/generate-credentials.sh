#!/bin/bash
# generate-credentials.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRAEFIK_DIR="$PROJECT_ROOT/infra/traefik"

# Load environment variables from .env file if it exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

# Request username
read -p "Enter username for main authentication (default: admin): " username
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

# Update main credentials for Traefik
update_env_credentials "$credentials" "$TRAEFIK_DIR/.env.dev"
update_env_credentials "$credentials" "$TRAEFIK_DIR/.env.prod"

# Update separate user and password variables
update_separate_credentials "$username" "$password" "MAIN_AUTHENTICATION_USER" "MAIN_AUTHENTICATION_PASSWORD" "$TRAEFIK_DIR/.env.dev"
update_separate_credentials "$username" "$password" "MAIN_AUTHENTICATION_USER" "MAIN_AUTHENTICATION_PASSWORD" "$TRAEFIK_DIR/.env.prod"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/uptime/.env.dev"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/uptime/.env.prod"
update_separate_credentials "$username" "$password" "N8N_BASIC_AUTH_USER" "N8N_BASIC_AUTH_PASSWORD" "$PROJECT_ROOT/apps/n8n/.env.dev"
update_separate_credentials "$username" "$password" "N8N_BASIC_AUTH_USER" "N8N_BASIC_AUTH_PASSWORD" "$PROJECT_ROOT/apps/n8n/.env.prod"
update_separate_credentials "$username" "$password" "MINIO_ROOT_USER" "MINIO_ROOT_PASSWORD" "$PROJECT_ROOT/apps/minio/.env.dev"
update_separate_credentials "$username" "$password" "MINIO_ROOT_USER" "MINIO_ROOT_PASSWORD" "$PROJECT_ROOT/apps/minio/.env.prod"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/loki/.env.dev"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/loki/.env.prod"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/grafana/.env.dev"
update_separate_credentials "$username" "$password" "ADMIN_USER" "ADMIN_PASSWORD" "$PROJECT_ROOT/apps/grafana/.env.prod"

log_success "Main authentication credentials generated successfully."
log_info "Username: $username"
log_info "Password: ********"
log_info "Please save these credentials securely."