#!/bin/bash
# replace-placeholders.sh - Template placeholder replacement utility
# This script provides functionality to replace placeholders in template files

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load utility functions
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

# ------------------------------------------------------------------------------
# Template processing functions
# ------------------------------------------------------------------------------

# Safe escape function for special characters
escape_for_replacement() {
    local input="$1"
    local type="${2:-default}"
    
    case "$type" in
        "credentials")
            # Escape $ characters in credentials to prevent variable expansion
            echo "$input" | awk '{gsub(/\$/, "\\$"); print}'
            ;;
        "email")
            # Escape @ and / characters in email addresses
            echo "$input" | awk '{gsub(/@/, "\\@"); gsub(/\//, "\\/"); print}'
            ;;
        "path")
            # Escape / characters in file paths
            echo "$input" | awk '{gsub(/\//, "\\/"); print}'
            ;;
        "url")
            # Escape / characters in URLs
            echo "$input" | awk '{gsub(/\//, "\\/"); print}'
            ;;
        *)
            # Default: escape / characters
            echo "$input" | awk '{gsub(/\//, "\\/"); print}'
            ;;
    esac
}

# Unified function to replace placeholders in templates
replace_placeholders() {
    local template="$1"
    local output="$2"
    local env_file="${3:-$PROJECT_ROOT/.env}"
    
    if [ ! -f "$template" ]; then
        log_error "Template not found: $template"
        return 1
    fi
    
    # Load environment variables if the file exists
    if [ -f "$env_file" ]; then
        source "$env_file"
    else
        log_warning "Environment file not found: $env_file"
    fi
    
    # Create temporary file
    local tmpfile=$(mktemp)
    cp "$template" "$tmpfile"

    # Escape special values using our helper function
    local escaped_users=""
    [ -n "$TRAEFIK_DASHBOARD_USERS" ] && escaped_users=$(escape_for_replacement "$TRAEFIK_DASHBOARD_USERS" "credentials")
    
    local escaped_email=""
    [ -n "$ACME_EMAIL" ] && escaped_email=$(escape_for_replacement "$ACME_EMAIL" "email")
    
    local escaped_acme_server=""
    [ -n "$ACME_SERVER" ] && escaped_acme_server=$(escape_for_replacement "$ACME_SERVER" "url")
    
    local escaped_domain=""
    [ -n "$DOMAIN" ] && escaped_domain=$(escape_for_replacement "$DOMAIN" "default")
    
    local escaped_staging_deploy_path=""
    [ -n "$STAGING_DEPLOY_PATH" ] && escaped_staging_deploy_path=$(escape_for_replacement "$STAGING_DEPLOY_PATH" "path")
    
    local escaped_production_deploy_path=""
    [ -n "$PRODUCTION_DEPLOY_PATH" ] && escaped_production_deploy_path=$(escape_for_replacement "$PRODUCTION_DEPLOY_PATH" "path")

    # Use perl for robust replacements (better than sed for complex patterns)
    # Special values that need escaping
    [ -n "$escaped_users" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD_USERS\}\}#$escaped_users#g" "$tmpfile"
    [ -n "$escaped_email" ] && perl -i -pe "s#\{\{ACME_EMAIL\}\}#$escaped_email#g" "$tmpfile"
    [ -n "$escaped_acme_server" ] && perl -i -pe "s#\{\{ACME_SERVER\}\}#$escaped_acme_server#g" "$tmpfile"
    [ -n "$escaped_domain" ] && perl -i -pe "s#\{\{DOMAIN\}\}#$escaped_domain#g" "$tmpfile"
    [ -n "$escaped_staging_deploy_path" ] && perl -i -pe "s#\{\{STAGING_DEPLOY_PATH\}\}#$escaped_staging_deploy_path#g" "$tmpfile"
    [ -n "$escaped_production_deploy_path" ] && perl -i -pe "s#\{\{PRODUCTION_DEPLOY_PATH\}\}#$escaped_production_deploy_path#g" "$tmpfile"

    # Simple variables (no special characters expected)
    [ -n "$TRAEFIK_DASHBOARD_AUTH_MIDDLEWARE" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD_AUTH_MIDDLEWARE\}\}#$TRAEFIK_DASHBOARD_AUTH_MIDDLEWARE#g" "$tmpfile"
    [ -n "$TRAEFIK_DASHBOARD_SECURITY_MIDDLEWARE" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD_SECURITY_MIDDLEWARE\}\}#$TRAEFIK_DASHBOARD_SECURITY_MIDDLEWARE#g" "$tmpfile"
    [ -n "$STAGING_MIDDLEWARE" ] && perl -i -pe "s#\{\{STAGING_MIDDLEWARE\}\}#$STAGING_MIDDLEWARE#g" "$tmpfile"
    [ -n "$PRODUCTION_MIDDLEWARE" ] && perl -i -pe "s#\{\{PRODUCTION_MIDDLEWARE\}\}#$PRODUCTION_MIDDLEWARE#g" "$tmpfile"
    [ -n "$TRAEFIK_DASHBOARD" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD\}\}#$TRAEFIK_DASHBOARD#g" "$tmpfile"
    [ -n "$TRAEFIK_INSECURE" ] && perl -i -pe "s#\{\{TRAEFIK_INSECURE\}\}#$TRAEFIK_INSECURE#g" "$tmpfile"
    [ -n "$LOG_LEVEL" ] && perl -i -pe "s#\{\{LOG_LEVEL\}\}#$LOG_LEVEL#g" "$tmpfile"
    [ -n "$LOG_FORMAT" ] && perl -i -pe "s#\{\{LOG_FORMAT\}\}#$LOG_FORMAT#g" "$tmpfile"
    [ -n "$ACCESSLOG_FORMAT" ] && perl -i -pe "s#\{\{ACCESSLOG_FORMAT\}\}#$ACCESSLOG_FORMAT#g" "$tmpfile"
    [ -n "$HEADERS_DEFAULT_MODE" ] && perl -i -pe "s#\{\{HEADERS_DEFAULT_MODE\}\}#$HEADERS_DEFAULT_MODE#g" "$tmpfile"
    [ -n "$HEADERS_USER_AGENT" ] && perl -i -pe "s#\{\{HEADERS_USER_AGENT\}\}#$HEADERS_USER_AGENT#g" "$tmpfile"
    [ -n "$HEADERS_AUTHORIZATION" ] && perl -i -pe "s#\{\{HEADERS_AUTHORIZATION\}\}#$HEADERS_AUTHORIZATION#g" "$tmpfile"
    [ -n "$HEADERS_CONTENT_TYPE" ] && perl -i -pe "s#\{\{HEADERS_CONTENT_TYPE\}\}#$HEADERS_CONTENT_TYPE#g" "$tmpfile"
    [ -n "$HTTP_PORT" ] && perl -i -pe "s#\{\{HTTP_PORT\}\}#$HTTP_PORT#g" "$tmpfile"
    [ -n "$HTTPS_PORT" ] && perl -i -pe "s#\{\{HTTPS_PORT\}\}#$HTTPS_PORT#g" "$tmpfile"
    [ -n "$HTTPS_PERMANENT_REDIRECT" ] && perl -i -pe "s#\{\{HTTPS_PERMANENT_REDIRECT\}\}#$HTTPS_PERMANENT_REDIRECT#g" "$tmpfile"
    [ -n "$CERT_RESOLVER" ] && perl -i -pe "s#\{\{CERT_RESOLVER\}\}#$CERT_RESOLVER#g" "$tmpfile"
    [ -n "$TLS_OPTIONS" ] && perl -i -pe "s#\{\{TLS_OPTIONS\}\}#$TLS_OPTIONS#g" "$tmpfile"
    [ -n "$TLS_MIN_VERSION" ] && perl -i -pe "s#\{\{TLS_MIN_VERSION\}\}#$TLS_MIN_VERSION#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_1" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_1\}\}#$TLS_CIPHER_SUITE_1#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_2" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_2\}\}#$TLS_CIPHER_SUITE_2#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_3" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_3\}\}#$TLS_CIPHER_SUITE_3#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_4" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_4\}\}#$TLS_CIPHER_SUITE_4#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_5" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_5\}\}#$TLS_CIPHER_SUITE_5#g" "$tmpfile"
    [ -n "$TLS_CIPHER_SUITE_6" ] && perl -i -pe "s#\{\{TLS_CIPHER_SUITE_6\}\}#$TLS_CIPHER_SUITE_6#g" "$tmpfile"
    [ -n "$DOCKER_ENDPOINT" ] && perl -i -pe "s#\{\{DOCKER_ENDPOINT\}\}#$DOCKER_ENDPOINT#g" "$tmpfile"
    [ -n "$DOCKER_EXPOSED_BY_DEFAULT" ] && perl -i -pe "s#\{\{DOCKER_EXPOSED_BY_DEFAULT\}\}#$DOCKER_EXPOSED_BY_DEFAULT#g" "$tmpfile"
    [ -n "$DOCKER_NETWORK" ] && perl -i -pe "s#\{\{DOCKER_NETWORK\}\}#$DOCKER_NETWORK#g" "$tmpfile"
    [ -n "$WATCH_DYNAMIC_CONF" ] && perl -i -pe "s#\{\{WATCH_DYNAMIC_CONF\}\}#$WATCH_DYNAMIC_CONF#g" "$tmpfile"
    [ -n "$TRAEFIK_DASHBOARD_HOST" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD_HOST\}\}#$TRAEFIK_DASHBOARD_HOST#g" "$tmpfile"
    [ -n "$TRAEFIK_ENTRYPOINT" ] && perl -i -pe "s#\{\{TRAEFIK_ENTRYPOINT\}\}#$TRAEFIK_ENTRYPOINT#g" "$tmpfile"
    [ -n "$HEADERS_FRAME_DENY" ] && perl -i -pe "s#\{\{HEADERS_FRAME_DENY\}\}#$HEADERS_FRAME_DENY#g" "$tmpfile"
    [ -n "$HEADERS_SSL_REDIRECT" ] && perl -i -pe "s#\{\{HEADERS_SSL_REDIRECT\}\}#$HEADERS_SSL_REDIRECT#g" "$tmpfile"
    [ -n "$HEADERS_XSS_FILTER" ] && perl -i -pe "s#\{\{HEADERS_XSS_FILTER\}\}#$HEADERS_XSS_FILTER#g" "$tmpfile"
    [ -n "$HEADERS_NOSNIFF" ] && perl -i -pe "s#\{\{HEADERS_NOSNIFF\}\}#$HEADERS_NOSNIFF#g" "$tmpfile"
    [ -n "$HEADERS_STS_SECONDS" ] && perl -i -pe "s#\{\{HEADERS_STS_SECONDS\}\}#$HEADERS_STS_SECONDS#g" "$tmpfile"
    [ -n "$HEADERS_STS_INCLUDE_SUBDOMAINS" ] && perl -i -pe "s#\{\{HEADERS_STS_INCLUDE_SUBDOMAINS\}\}#$HEADERS_STS_INCLUDE_SUBDOMAINS#g" "$tmpfile"
    [ -n "$HEADERS_STS_PRELOAD" ] && perl -i -pe "s#\{\{HEADERS_STS_PRELOAD\}\}#$HEADERS_STS_PRELOAD#g" "$tmpfile"
    [ -n "$RATE_LIMIT_AVERAGE" ] && perl -i -pe "s#\{\{RATE_LIMIT_AVERAGE\}\}#$RATE_LIMIT_AVERAGE#g" "$tmpfile"
    [ -n "$RATE_LIMIT_BURST" ] && perl -i -pe "s#\{\{RATE_LIMIT_BURST\}\}#$RATE_LIMIT_BURST#g" "$tmpfile"
    [ -n "$RATE_LIMIT_PERIOD" ] && perl -i -pe "s#\{\{RATE_LIMIT_PERIOD\}\}#$RATE_LIMIT_PERIOD#g" "$tmpfile"
    [ -n "$STAGING_DOMAIN" ] && perl -i -pe "s#\{\{STAGING_DOMAIN\}\}#$STAGING_DOMAIN#g" "$tmpfile"
    [ -n "$STAGING_ENTRYPOINT" ] && perl -i -pe "s#\{\{STAGING_ENTRYPOINT\}\}#$STAGING_ENTRYPOINT#g" "$tmpfile"
    [ -n "$STAGING_SERVICE" ] && perl -i -pe "s#\{\{STAGING_SERVICE\}\}#$STAGING_SERVICE#g" "$tmpfile"
    [ -n "$STAGING_SERVER" ] && perl -i -pe "s#\{\{STAGING_SERVER\}\}#$STAGING_SERVER#g" "$tmpfile"
    [ -n "$STAGING_PORT" ] && perl -i -pe "s#\{\{STAGING_PORT\}\}#$STAGING_PORT#g" "$tmpfile"
    [ -n "$PRODUCTION_DOMAIN" ] && perl -i -pe "s#\{\{PRODUCTION_DOMAIN\}\}#$PRODUCTION_DOMAIN#g" "$tmpfile"
    [ -n "$PRODUCTION_ENTRYPOINT" ] && perl -i -pe "s#\{\{PRODUCTION_ENTRYPOINT\}\}#$PRODUCTION_ENTRYPOINT#g" "$tmpfile"
    [ -n "$PRODUCTION_SERVICE" ] && perl -i -pe "s#\{\{PRODUCTION_SERVICE\}\}#$PRODUCTION_SERVICE#g" "$tmpfile"
    [ -n "$PRODUCTION_SERVER" ] && perl -i -pe "s#\{\{PRODUCTION_SERVER\}\}#$PRODUCTION_SERVER#g" "$tmpfile"
    [ -n "$PRODUCTION_PORT" ] && perl -i -pe "s#\{\{PRODUCTION_PORT\}\}#$PRODUCTION_PORT#g" "$tmpfile"
    [ -n "$PRODUCTION_DEPLOY_PATH" ] && perl -i -pe "s#\{\{PRODUCTION_DEPLOY_PATH\}\}#$PRODUCTION_DEPLOY_PATH#g" "$tmpfile"
    
    # Ansible-specific variables
    [ -n "$ARTIFACT_NAME" ] && perl -i -pe "s#\{\{ARTIFACT_NAME\}\}#$ARTIFACT_NAME#g" "$tmpfile"
    [ -n "$DISABLE_HTTPS" ] && perl -i -pe "s#\{\{DISABLE_HTTPS\}\}#$DISABLE_HTTPS#g" "$tmpfile"
    [ -n "$STAGING_HOSTNAME" ] && perl -i -pe "s#\{\{STAGING_HOSTNAME\}\}#$STAGING_HOSTNAME#g" "$tmpfile"
    [ -n "$STAGING_HOST_IP" ] && perl -i -pe "s#\{\{STAGING_HOST_IP\}\}#$STAGING_HOST_IP#g" "$tmpfile"
    [ -n "$STAGING_HOST_USER" ] && perl -i -pe "s#\{\{STAGING_HOST_USER\}\}#$STAGING_HOST_USER#g" "$tmpfile"
    [ -n "$STAGING_HOST_PORT" ] && perl -i -pe "s#\{\{STAGING_HOST_PORT\}\}#$STAGING_HOST_PORT#g" "$tmpfile"
    [ -n "$PRODUCTION_HOSTNAME" ] && perl -i -pe "s#\{\{PRODUCTION_HOSTNAME\}\}#$PRODUCTION_HOSTNAME#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_IP" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_IP\}\}#$PRODUCTION_HOST_IP#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_USER" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_USER\}\}#$PRODUCTION_HOST_USER#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_PORT" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_PORT\}\}#$PRODUCTION_HOST_PORT#g" "$tmpfile"
    [ -n "$ANSIBLE_SSH_USER" ] && perl -i -pe "s#\{\{ANSIBLE_SSH_USER\}\}#$ANSIBLE_SSH_USER#g" "$tmpfile"
    [ -n "$ANSIBLE_HOST" ] && perl -i -pe "s#\{\{ANSIBLE_HOST\}\}#$ANSIBLE_HOST#g" "$tmpfile"
    [ -n "$ANSIBLE_HOST_PORT" ] && perl -i -pe "s#\{\{ANSIBLE_HOST_PORT\}\}#$ANSIBLE_HOST_PORT#g" "$tmpfile"
    
    # App specific variables
    [ -n "$IMAGE_NAME" ] && perl -i -pe "s#\{\{IMAGE_NAME\}\}#$IMAGE_NAME#g" "$tmpfile"
    [ -n "$CONTAINER_NAME" ] && perl -i -pe "s#\{\{CONTAINER_NAME\}\}#$CONTAINER_NAME#g" "$tmpfile"
    [ -n "$APP_BLOG_NAME" ] && perl -i -pe "s#\{\{APP_BLOG_NAME\}\}#$APP_BLOG_NAME#g" "$tmpfile"
    [ -n "$APP_BLOG_PORT" ] && perl -i -pe "s#\{\{APP_BLOG_PORT\}\}#$APP_BLOG_PORT#g" "$tmpfile"
    [ -n "$APP_BLOG_HOST" ] && perl -i -pe "s#\{\{APP_BLOG_HOST\}\}#$APP_BLOG_HOST#g" "$tmpfile"
    [ -n "$APP_WEB_NAME" ] && perl -i -pe "s#\{\{APP_WEB_NAME\}\}#$APP_WEB_NAME#g" "$tmpfile"
    [ -n "$APP_WEB_PORT" ] && perl -i -pe "s#\{\{APP_WEB_PORT\}\}#$APP_WEB_PORT#g" "$tmpfile"
    [ -n "$APP_WEB_HOST" ] && perl -i -pe "s#\{\{APP_WEB_HOST\}\}#$APP_WEB_HOST#g" "$tmpfile"
    [ -n "$APP_API_NAME" ] && perl -i -pe "s#\{\{APP_API_NAME\}\}#$APP_API_NAME#g" "$tmpfile"
    [ -n "$APP_API_PORT" ] && perl -i -pe "s#\{\{APP_API_PORT\}\}#$APP_API_PORT#g" "$tmpfile"
    [ -n "$APP_API_HOST" ] && perl -i -pe "s#\{\{APP_API_HOST\}\}#$APP_API_HOST#g" "$tmpfile"  
    [ -n "$APP_N8N_NAME" ] && perl -i -pe "s#\{\{APP_N8N_NAME\}\}#$APP_N8N_NAME#g" "$tmpfile"
    [ -n "$APP_N8N_PORT" ] && perl -i -pe "s#\{\{APP_N8N_PORT\}\}#$APP_N8N_PORT#g" "$tmpfile"
    [ -n "$APP_N8N_HOST" ] && perl -i -pe "s#\{\{APP_N8N_HOST\}\}#$APP_N8N_HOST#g" "$tmpfile"
    [ -n "$APP_GRAFANA_NAME" ] && perl -i -pe "s#\{\{APP_GRAFANA_NAME\}\}#$APP_GRAFANA_NAME#g" "$tmpfile"
    [ -n "$APP_GRAFANA_PORT" ] && perl -i -pe "s#\{\{APP_GRAFANA_PORT\}\}#$APP_GRAFANA_PORT#g" "$tmpfile"
    [ -n "$APP_GRAFANA_HOST" ] && perl -i -pe "s#\{\{APP_GRAFANA_HOST\}\}#$APP_GRAFANA_HOST#g" "$tmpfile"
    [ -n "$APP_LOKI_NAME" ] && perl -i -pe "s#\{\{APP_LOKI_NAME\}\}#$APP_LOKI_NAME#g" "$tmpfile"
    [ -n "$APP_LOKI_PORT" ] && perl -i -pe "s#\{\{APP_LOKI_PORT\}\}#$APP_LOKI_PORT#g" "$tmpfile"
    [ -n "$APP_LOKI_HOST" ] && perl -i -pe "s#\{\{APP_LOKI_HOST\}\}#$APP_LOKI_HOST#g" "$tmpfile"
    [ -n "$APP_UPTIME_KUMA_NAME" ] && perl -i -pe "s#\{\{APP_UPTIME_KUMA_NAME\}\}#$APP_UPTIME_KUMA_NAME#g" "$tmpfile"
    [ -n "$APP_UPTIME_KUMA_PORT" ] && perl -i -pe "s#\{\{APP_UPTIME_KUMA_PORT\}\}#$APP_UPTIME_KUMA_PORT#g" "$tmpfile"
    [ -n "$APP_UPTIME_KUMA_HOST" ] && perl -i -pe "s#\{\{APP_UPTIME_KUMA_HOST\}\}#$APP_UPTIME_KUMA_HOST#g" "$tmpfile"
    [ -n "$APP_PORTAINER_NAME" ] && perl -i -pe "s#\{\{APP_PORTAINER_NAME\}\}#$APP_PORTAINER_NAME#g" "$tmpfile"
    [ -n "$APP_PORTAINER_PORT" ] && perl -i -pe "s#\{\{APP_PORTAINER_PORT\}\}#$APP_PORTAINER_PORT#g" "$tmpfile"
    [ -n "$APP_PORTAINER_HOST" ] && perl -i -pe "s#\{\{APP_PORTAINER_HOST\}\}#$APP_PORTAINER_HOST#g" "$tmpfile"
    [ -n "$APP_WIKI_NAME" ] && perl -i -pe "s#\{\{APP_WIKI_NAME\}\}#$APP_WIKI_NAME#g" "$tmpfile"
    [ -n "$APP_WIKI_PORT" ] && perl -i -pe "s#\{\{APP_WIKI_PORT\}\}#$APP_WIKI_PORT#g" "$tmpfile"
    [ -n "$APP_WIKI_HOST" ] && perl -i -pe "s#\{\{APP_WIKI_HOST\}\}#$APP_WIKI_HOST#g" "$tmpfile"

    # Server variables
    [ -n "$DNS_PROVIDER" ] && perl -i -pe "s#\{\{DNS_PROVIDER\}\}#$DNS_PROVIDER#g" "$tmpfile"
    [ -n "$DNS_DELAY_BEFORE_CHECK" ] && perl -i -pe "s#\{\{DNS_DELAY_BEFORE_CHECK\}\}#$DNS_DELAY_BEFORE_CHECK#g" "$tmpfile"
    [ -n "$DNS_RESOLVER_1" ] && perl -i -pe "s#\{\{DNS_RESOLVER_1\}\}#$DNS_RESOLVER_1#g" "$tmpfile"
    [ -n "$DNS_RESOLVER_2" ] && perl -i -pe "s#\{\{DNS_RESOLVER_2\}\}#$DNS_RESOLVER_2#g" "$tmpfile"
    # Move the processed file to the output location
    mv "$tmpfile" "$output"
    return 0
}

# Process all templates in a directory
process_templates_in_directory() {
    local templates_dir="$1"
    local output_dir="$2"
    local file_pattern="${3:-*.template.yml}"
    local env_file="${4:-$PROJECT_ROOT/.env}"
    
    if [ ! -d "$templates_dir" ]; then
        log_error "Templates directory not found: $templates_dir"
        return 1
    fi
    
    mkdir -p "$output_dir"
    
    local processed_count=0
    for template_file in "$templates_dir"/$file_pattern; do
        # Skip if file doesn't exist
        [ ! -f "$template_file" ] && continue
        
        # Extract base name without .template.yml extension
        local base_name=$(basename "$template_file" .template.yml)
        local output_file="$output_dir/$base_name.yml"
        
        log_info "Processing template: $(basename "$template_file")"
        
        if replace_placeholders "$template_file" "$output_file" "$env_file"; then
            log_success "Generated: $output_file"
            ((processed_count++))
        else
            log_error "Failed to generate: $output_file"
        fi
    done
    
    if [ $processed_count -eq 0 ]; then
        log_warning "No templates found matching pattern: $file_pattern"
        return 1
    fi
    
    log_success "Processed $processed_count template(s)"
    return 0
}

# ------------------------------------------------------------------------------
# Main execution (if script is run directly)
# ------------------------------------------------------------------------------

# Check if script is being run directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Usage function
    usage() {
        echo "Usage: $0 <template_file> <output_file> [env_file]"
        echo "       $0 --process-directory <templates_dir> <output_dir> [file_pattern] [env_file]"
        echo ""
        echo "Examples:"
        echo "  $0 config.template.yml config.yml .env"
        echo "  $0 --process-directory templates/ output/ '*.template.yml' .env"
        exit 1
    }
    
    # Check arguments
    if [ $# -lt 2 ]; then
        usage
    fi
    
    # Process directory option
    if [ "$1" = "--process-directory" ]; then
        if [ $# -lt 3 ]; then
            usage
        fi
        
        templates_dir="$2"
        output_dir="$3"
        file_pattern="${4:-*.template.yml}"
        env_file="${5:-$PROJECT_ROOT/.env}"
        
        process_templates_in_directory "$templates_dir" "$output_dir" "$file_pattern" "$env_file"
    else
        # Single file processing
        template="$1"
        output="$2"
        env_file="${3:-$PROJECT_ROOT/.env}"
        
        replace_placeholders "$template" "$output" "$env_file"
    fi
fi