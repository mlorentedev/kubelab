#!/bin/bash
# generate-traefik-config.sh

# Get the directory of the script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Load environment variables from .env file if it exists
[ -f "./scripts/utils.sh" ] && source ./scripts/utils.sh
[ -f "../../.env" ] && source ../../.env

# Check if .env is sourced
if [ -z "$TRAEFIK_DASHBOARD" ]; then
  log_error "Error: .env file not sourced. Please ensure it exists and contains the necessary variables."
  exit 1
fi

# Set default values for Traefik configuration
DOMAIN=${DOMAIN}
TRAEFIK_DASHBOARD=${TRAEFIK_DASHBOARD}
TRAEFIK_INSECURE=${TRAEFIK_INSECURE}
ACME_SERVER=${ACME_SERVER}
ACME_EMAIL=${ACME_EMAIL}
DISABLE_HTTPS=${DISABLE_HTTPS}

# Create the traefik directory if it doesn't exist
log_info "Generating Traefik configuration..."
mkdir -p traefik
touch traefik/traefik.yml

# Choose the appropriate template based on DISABLE_HTTPS
if [ "$DISABLE_HTTPS" = "true" ]; then
  TEMPLATE_FILE="traefik/traefik.template.http.yml"
  log_info "Using HTTP template for Traefik configuration."
else
  TEMPLATE_FILE="traefik/traefik.template.https.yml"
  log_info "Using HTTPS template for Traefik configuration."
fi

# Generate the Traefik configuration file from the template
cat $TEMPLATE_FILE | \
  sed "s/{{DOMAIN}}/$DOMAIN/g" | \
  sed "s/{{TRAEFIK_DASHBOARD}}/$TRAEFIK_DASHBOARD/g" | \
  sed "s/{{TRAEFIK_INSECURE}}/$TRAEFIK_INSECURE/g" | \
  sed "s#{{ACME_SERVER}}#$ACME_SERVER#g" | \
  sed "s/{{ACME_EMAIL}}/$ACME_EMAIL/g" > traefik/traefik.yml

log_success "Traefik configuration generated successfully."