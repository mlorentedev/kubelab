#!/bin/bash
# generate-traefik-config.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRAEFIK_DIR="$PROJECT_ROOT/infra/traefik"
TEMPLATES_DIR="$TRAEFIK_DIR/templates"
DYNAMIC_CONF_DIR="$TRAEFIK_DIR/dynamic"

# Load utility functions if utils.sh exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

# Load environment variables from .env file if it exists
env_file="$TRAEFIK_DIR/.env"
[ -f "$env_file" ] && source "$env_file"

# Check if .env is sourced
required_vars=("TRAEFIK_DASHBOARD" "ACME_EMAIL" "ENVIRONMENT" "TRAEFIK_DASHBOARD_USERS")
if ! verify_required_vars "${required_vars[@]}"; then
    if [ -z "$TRAEFIK_DASHBOARD_USERS" ]; then
        log_error "TRAEFIK_DASHBOARD_USERS not found. Please run 'make generate-auth' first."
    fi
    exit 1
fi

# Create directories if they don't exist
mkdir -p "$DYNAMIC_CONF_DIR" "$TRAEFIK_DIR/logs"

# Ensure templates directory exists
if [ ! -d "$TEMPLATES_DIR" ]; then
    log_error "Templates directory not found: $TEMPLATES_DIR"
    exit 1
fi

# Process main Traefik configuration
log_info "Generating main Traefik configuration..."

# Determine which template to use based on DISABLE_HTTPS
if [ "${ENVIRONMENT}" = "local" ]; then
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.http.template.yml"
    log_info "Using HTTP template for Traefik configuration."
else
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.https.template.yml"
    log_info "Using HTTPS template for Traefik configuration."
fi

if [ ! -f "$MAIN_TEMPLATE" ]; then
    log_error "Error: Template file not found: $MAIN_TEMPLATE"
    exit 1
fi

# Process the main template and replace placeholders
replace_placeholders "$MAIN_TEMPLATE" "$TRAEFIK_DIR/traefik.yml" "$env_file"
log_success "Generated: $TRAEFIK_DIR/traefik.yml"

# Process all dynamic configuration templates
log_info "Generating dynamic configuration files..."

# Process each template file
for template_file in "$TEMPLATES_DIR"/*.template.yml; do
    # Skip if file doesn't exist or isn't a regular file
    [ ! -f "$template_file" ] && continue
    [ "$template_file" = "$MAIN_TEMPLATE" ] && continue

    # Extract the base filename without path and .template.yml extension
    base_name=$(basename "$template_file" .template.yml)

    # Skip HTTP or HTTPS templates 
    case "$base_name" in
        traefik.http|traefik.https)
            log_info "Skipping $base_name configuration."
            continue
            ;;
    esac

    if [ "${ENVIRONMENT}" = "local" ]; then
        case "$base_name" in
            acme-challenge|tls)
                log_info "Skipping $base_name configuration in local environment."
                continue
                ;;
        esac
    fi

    output_file="$DYNAMIC_CONF_DIR/$base_name.yml"
    
    log_info "Processing template: $(basename "$template_file")"
    
    # Process the template
    if replace_placeholders "$template_file" "$output_file" "$env_file"; then
        if [ "${ENVIRONMENT}" = "local" ]; then
            # Remove any line with 'tls:' or 'certResolver'
            sed -i '/^[[:space:]]*tls:/d' "$output_file"
            sed -i '/^[[:space:]]*certResolver:/d' "$output_file"
        fi
        log_success "Generated: $output_file"
    else
        log_error "Failed to generate: $output_file"
    fi
done

# If acme.json doesn't exist, create it with proper permissions
if [ ! -f "$TRAEFIK_DIR/certs/acme.json" ]; then
    log_info "Creating acme.json file with correct permissions..."
    create_secure_file "$TRAEFIK_DIR/certs/acme.json" "600"
fi

log_success "Traefik configuration generated successfully."
log_info "Static configuration: $TRAEFIK_DIR/traefik.yml"
log_info "Dynamic configuration: $DYNAMIC_CONF_DIR/"
log_info "To apply these changes, restart the Traefik service."