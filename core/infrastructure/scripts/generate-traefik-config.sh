#!/bin/bash
# generate-traefik-config.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TRAEFIK_DIR="$SCRIPT_DIR/../traefik"
TEMPLATES_DIR="$TRAEFIK_DIR/templates"
DYNAMIC_CONF_DIR="$TRAEFIK_DIR/dynamic_conf"

# Load environment variables from .env file if it exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"
[ -f "$PROJECT_ROOT/.env" ] && source "$PROJECT_ROOT/.env"

# Check if .env is sourced
if [ -z "$TRAEFIK_DASHBOARD" ]; then
  log_error "Error: .env file not sourced. Please ensure it exists and contains the necessary variables."
  exit 1
fi

# Check if required environment variables are set
if [ -z "$DOMAIN" ]; then
    log_error "Error: DOMAIN variable not set in .env file."
    exit 1
fi

# Create directories if they don't exist
mkdir -p "$DYNAMIC_CONF_DIR"
mkdir -p "$TRAEFIK_DIR/logs"
mkdir -p "$TRAEFIK_DIR/ssl/private"
mkdir -p "$TRAEFIK_DIR/ssl/certs"

# Ensure templates directory exists
if [ ! -d "$TEMPLATES_DIR" ]; then
    log_error "Error: Templates directory not found: $TEMPLATES_DIR"
    exit 1
fi

# Process main Traefik configuration
log_info "Generating main Traefik configuration..."

# Determine which template to use based on DISABLE_HTTPS
if [ "${DISABLE_HTTPS}" = "true" ]; then
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.http.template.yml"
    log_info "Using HTTP template for Traefik configuration."
else
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.https.template.yml"
    log_info "Using HTTPS template for Traefik configuration."
fi

# Check if template exists
if [ ! -f "$MAIN_TEMPLATE" ]; then
    log_error "Error: Template file not found: $MAIN_TEMPLATE"
    exit 1
fi

# Function to safely replace placeholders
replace_placeholders() {
    local template="$1"
    local output="$2"
    
    # Create a temporary file for processing
    local tmpfile=$(mktemp)
    
    # Copy template to temporary file
    cp "$template" "$tmpfile"
    
    # Replace each placeholder with its value
    perl -p -e "s#{{DOMAIN}}#${DOMAIN//\//\\/}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_DASHBOARD}}#${TRAEFIK_DASHBOARD}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_INSECURE}}#${TRAEFIK_INSECURE}#g" -i "$tmpfile"
    perl -p -e "s#{{ACME_SERVER}}#${ACME_SERVER//\//\\/}#g" -i "$tmpfile"
    perl -p -e "s#{{ACME_EMAIL}}#${ACME_EMAIL//\//\\/}#g" -i "$tmpfile"
    perl -p -e "s#{{LOG_LEVEL}}#${LOG_LEVEL}#g" -i "$tmpfile"
    perl -p -e "s#{{LOG_FORMAT}}#${LOG_FORMAT}#g" -i "$tmpfile"
    perl -p -e "s#{{ACCESSLOG_FORMAT}}#${ACCESSLOG_FORMAT}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_DEFAULT_MODE}}#${HEADERS_DEFAULT_MODE}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_USER_AGENT}}#${HEADERS_USER_AGENT}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_AUTHORIZATION}}#${HEADERS_AUTHORIZATION}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_CONTENT_TYPE}}#${HEADERS_CONTENT_TYPE}#g" -i "$tmpfile"
    perl -p -e "s#{{HTTP_PORT}}#${HTTP_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{HTTPS_PORT}}#${HTTPS_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{HTTPS_PERMANENT_REDIRECT}}#${HTTPS_PERMANENT_REDIRECT}#g" -i "$tmpfile"
    perl -p -e "s#{{CERT_RESOLVER}}#${CERT_RESOLVER}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_OPTIONS}}#${TLS_OPTIONS}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_MIN_VERSION}}#${TLS_MIN_VERSION}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_1}}#${TLS_CIPHER_SUITE_1}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_2}}#${TLS_CIPHER_SUITE_2}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_3}}#${TLS_CIPHER_SUITE_3}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_4}}#${TLS_CIPHER_SUITE_4}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_5}}#${TLS_CIPHER_SUITE_5}#g" -i "$tmpfile"
    perl -p -e "s#{{TLS_CIPHER_SUITE_6}}#${TLS_CIPHER_SUITE_6}#g" -i "$tmpfile"
    perl -p -e "s#{{DOCKER_ENDPOINT}}#${DOCKER_ENDPOINT}#g" -i "$tmpfile"
    perl -p -e "s#{{DOCKER_EXPOSED_BY_DEFAULT}}#${DOCKER_EXPOSED_BY_DEFAULT}#g" -i "$tmpfile"
    perl -p -e "s#{{DOCKER_NETWORK}}#${DOCKER_NETWORK}#g" -i "$tmpfile"
    perl -p -e "s#{{WATCH_DYNAMIC_CONF}}#${WATCH_DYNAMIC_CONF}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_DASHBOARD_HOST}}#${TRAEFIK_DASHBOARD_HOST}#g" -i "$tmpfile"
    perl -p -e "s#{{DASHBOARD_ENTRYPOINT}}#${DASHBOARD_ENTRYPOINT}#g" -i "$tmpfile"
    perl -p -e "s#{{DASHBOARD_AUTH_MIDDLEWARE}}#${DASHBOARD_AUTH_MIDDLEWARE}#g" -i "$tmpfile"
    perl -p -e "s#{{DASHBOARD_SECURITY_MIDDLEWARE}}#${DASHBOARD_SECURITY_MIDDLEWARE}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_FRAME_DENY}}#${HEADERS_FRAME_DENY}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_SSL_REDIRECT}}#${HEADERS_SSL_REDIRECT}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_XSS_FILTER}}#${HEADERS_XSS_FILTER}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_NOSNIFF}}#${HEADERS_NOSNIFF}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_STS_SECONDS}}#${HEADERS_STS_SECONDS}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_STS_INCLUDE_SUBDOMAINS}}#${HEADERS_STS_INCLUDE_SUBDOMAINS}#g" -i "$tmpfile"
    perl -p -e "s#{{HEADERS_STS_PRELOAD}}#${HEADERS_STS_PRELOAD}#g" -i "$tmpfile"
    perl -p -e "s#{{DEFAULT_CERT_FILE}}#${DEFAULT_CERT_FILE}#g" -i "$tmpfile"
    perl -p -e "s#{{DEFAULT_KEY_FILE}}#${DEFAULT_KEY_FILE}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_HOST}}#${PRODUCTION_HOST}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_ENTRYPOINT}}#${PRODUCTION_ENTRYPOINT}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_SERVICE}}#${PRODUCTION_SERVICE}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_SERVER}}#${PRODUCTION_SERVER}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_PORT}}#${PRODUCTION_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_MIDDLEWARE}}#${PRODUCTION_MIDDLEWARE}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_HOST}}#${STAGING_HOST}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_ENTRYPOINT}}#${STAGING_ENTRYPOINT}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_SERVICE}}#${STAGING_SERVICE}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_SERVER}}#${STAGING_SERVER}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_PORT}}#${STAGING_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_MIDDLEWARE}}#${STAGING_MIDDLEWARE}#g" -i "$tmpfile"

    # Move the processed file to the output location
    mv "$tmpfile" "$output"
}

# Process main Traefik configuration
log_info "Generating main Traefik configuration..."

# Determine which template to use based on DISABLE_HTTPS
if [ "${DISABLE_HTTPS}" = "true" ]; then
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.http.template.yml"
    log_info "Using HTTP template for Traefik configuration."
else
    MAIN_TEMPLATE="$TEMPLATES_DIR/traefik.https.template.yml"
    log_info "Using HTTPS template for Traefik configuration."
fi

# Check if template exists
if [ ! -f "$MAIN_TEMPLATE" ]; then
    log_error "Error: Template file not found: $MAIN_TEMPLATE"
    exit 1
fi

# Process the main configuration template
replace_placeholders "$MAIN_TEMPLATE" "$TRAEFIK_DIR/traefik.yml"

# Process all dynamic configuration templates
log_info "Generating dynamic configuration files..."

# Process each template file
for template_file in "$TEMPLATES_DIR"/*.template.yml; do
    # Skip if file doesn't exist or isn't a regular file
    [ ! -f "$template_file" ] && continue
    
    # Extract the base filename without path and .template.yml extension
    base_name=$(basename "$template_file" .template.yml)
    output_file="$DYNAMIC_CONF_DIR/$base_name.yml"
    
    log_info "Processing template: $(basename "$template_file")"
    
    # Process the template
    replace_placeholders "$template_file" "$output_file"
    
    log_success "Generated: $output_file"
done

# If acme.json doesn't exist, create it with proper permissions
if [ ! -f "$TRAEFIK_DIR/acme.json" ]; then
    log_info "Creating acme.json file with correct permissions..."
    touch "$TRAEFIK_DIR/acme.json"
    chmod 600 "$TRAEFIK_DIR/acme.json"
fi

log_success "Traefik configuration generated successfully."
log_info "Configuration files are located in: $TRAEFIK_DIR"
log_info "Main configuration: $TRAEFIK_DIR/traefik.yml"
log_info "Dynamic configuration: $DYNAMIC_CONF_DIR/"
log_info "To apply these changes, restart the Traefik service."