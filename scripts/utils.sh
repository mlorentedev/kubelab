#!/bin/bash
# utils.sh - Common utilities for scripting
# This script is sourced by other scripts to provide common functionality

# ------------------------------------------------------------------------------
# Output colors
# ------------------------------------------------------------------------------
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export PURPLE='\033[0;35m'
export CYAN='\033[0;36m'
export NC='\033[0m' # No Color

# ------------------------------------------------------------------------------
# Logging functions
# ------------------------------------------------------------------------------

# Log an info message
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Log a success message
log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Log a warning message
log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Log an error message
log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Exit with error message and code
exit_error() {
    local message=$1
    local code=${2:-1} # Default exit code is 1
    
    log_error "$message"
    exit $code
}

# ------------------------------------------------------------------------------
# Environment validation functions
# ------------------------------------------------------------------------------

# Load environment variables from .env file
load_env_file() {
    local env_file="$1"
    
    # Check if file exists
    if [ ! -f "$env_file" ]; then
        log_warning "Environment file not found: $env_file"
        return 1
    fi

    # Read file line by line, handling multiline and quoted values
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        [[ "$line" =~ ^\s*#.* ]] && continue
        [[ -z "$line" ]] && continue

        # Extract key and value
        key=$(echo "$line" | cut -d '=' -f1)
        value=$(echo "$line" | cut -d '=' -f2-)

        # Remove leading/trailing whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)

        # Remove surrounding quotes if present
        value="${value%\"}"
        value="${value#\"}"

        # Export the variable, preserving multiline content
        export "$key=$value"
    done < "$env_file"
}

debug_print_env() {
    echo "=== Loaded Environment Variables ==="
    
    # Print all variables from the .env file
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^\s*#.* ]] && continue
        [[ -z "$key" ]] && continue
        
        # Print the key and its value
        echo "${key}=${value}"
    done < "$ENV_FILE"
}

# ------------------------------------------------------------------------------
# Server connectivity functions
# ------------------------------------------------------------------------------

# Check SSH connectivity to the server
check_server_connectivity() {
    local server=$1
    
    log_info "Checking SSH connectivity to $server..."
    
    if ! ssh -q -o BatchMode=yes -o ConnectTimeout=5 "$server" exit 2>/dev/null; then
        exit_error "Cannot connect to server $server. Verify that the server is correctly configured and SSH key is in place."
    fi
    
    log_success "Server connection successful."
}

# ------------------------------------------------------------------------------
# Dependency check functions
# ------------------------------------------------------------------------------

# Check if a command is available
check_command() {
    local cmd=$1
    local package=${2:-$cmd}
    
    if ! command -v "$cmd" &> /dev/null; then
        log_error "$cmd not found. Please install $package."
        return 1
    fi
    
    return 0
}

# Check all required commands
check_dependencies() {
    local deps=("$@")
    local missing=0
    
    for dep in "${deps[@]}"; do
        if ! check_command "$dep"; then
            missing=1
        fi
    done
    
    if [ $missing -eq 1 ]; then
        exit_error "Missing required dependencies. Please install them and try again."
    fi
}

verify_required_vars() {
    local required_vars=("$@")
    local missing_vars=()

    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            missing_vars+=("$var")
        fi
    done

    if [ ${#missing_vars[@]} -gt 0 ]; then
        log_error "Missing required variables in .env:"
        for var in "${missing_vars[@]}"; do
            echo "  - $var"
        done
        return 1
    fi

    return 0
}

# ------------------------------------------------------------------------------
# User confirmation functions
# ------------------------------------------------------------------------------

# Ask for user confirmation
confirm_action() {
    local message=${1:-"Are you sure you want to continue?"}
    
    echo -e "${YELLOW}$message (y/n)${NC}"
    read -r confirm
    
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        log_warning "Operation cancelled."
        return 1
    fi
    
    return 0
}

# ------------------------------------------------------------------------------
# File and backup functions
# ------------------------------------------------------------------------------

# Create a backup of a file
backup_file() {
    local file=$1
    local backup="${file}.$(date +%Y%m%d%H%M%S).bak"
    
    if [ -f "$file" ]; then
        log_info "Creating backup of $file..."
        cp "$file" "$backup"
        log_success "Backup created: $backup"
    else
        log_warning "File $file does not exist, no backup created."
    fi
}

# Create a timestamp
get_timestamp() {
    echo "$(date +%Y%m%d%H%M%S)"
}

# ------------------------------------------------------------------------------
# Generate basic auth credentials
# ------------------------------------------------------------------------------

# Generate basic auth credentials
generate_basic_auth() {
    local username=$1
    local password=$2
    
    # Generate password hash using htpasswd or openssl
    if command -v htpasswd > /dev/null; then
        local hashed_password=$(htpasswd -nb "$username" "$password")
        echo "$hashed_password"
    else
        local hashed_password=$(openssl passwd -apr1 "$password")
        echo "${username}:${hashed_password}"
    fi
}

# Update environment files with credentials (using single quotes to prevent expansion)
update_env_credentials() {
    local credentials="$1"
    local env_files=("$@")
    # Remove first argument (credentials) to get just the file list
    env_files=("${env_files[@]:1}")
    
    for env_file in "${env_files[@]}"; do
        if [ -f "$env_file" ]; then
            if grep -q "TRAEFIK_DASHBOARD_USERS=" "$env_file"; then
                # Replace existing line - using single quotes to prevent $ expansion
                sed -i "s|TRAEFIK_DASHBOARD_USERS=.*|TRAEFIK_DASHBOARD_USERS='$credentials'|" "$env_file"
                log_success "Updated credentials in $env_file"
            else
                # Add new line - using single quotes to prevent $ expansion
                echo "TRAEFIK_DASHBOARD_USERS='$credentials'" >> "$env_file"
                log_success "Added credentials to $env_file"
            fi
        else
            log_warning "File $env_file doesn't exist, skipping."
        fi
    done
}

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
    [ -n "$TRAEFIK_DASHBOARD_ENTRYPOINT" ] && perl -i -pe "s#\{\{TRAEFIK_DASHBOARD_ENTRYPOINT\}\}#$TRAEFIK_DASHBOARD_ENTRYPOINT#g" "$tmpfile"
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

    # Ansible-specific variables
    [ -n "$ARTIFACT_NAME" ] && perl -i -pe "s#\{\{ARTIFACT_NAME\}\}#$ARTIFACT_NAME#g" "$tmpfile"
    [ -n "$DISABLE_HTTPS" ] && perl -i -pe "s#\{\{DISABLE_HTTPS\}\}#$DISABLE_HTTPS#g" "$tmpfile"
    [ -n "$STAGING_HOST_NAME" ] && perl -i -pe "s#\{\{STAGING_HOST_NAME\}\}#$STAGING_HOST_NAME#g" "$tmpfile"
    [ -n "$STAGING_HOST_IP" ] && perl -i -pe "s#\{\{STAGING_HOST_IP\}\}#$STAGING_HOST_IP#g" "$tmpfile"
    [ -n "$STAGING_HOST_USER" ] && perl -i -pe "s#\{\{STAGING_HOST_USER\}\}#$STAGING_HOST_USER#g" "$tmpfile"
    [ -n "$STAGING_HOST_PORT" ] && perl -i -pe "s#\{\{STAGING_HOST_PORT\}\}#$STAGING_HOST_PORT#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_NAME" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_NAME\}\}#$PRODUCTION_HOST_NAME#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_IP" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_IP\}\}#$PRODUCTION_HOST_IP#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_USER" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_USER\}\}#$PRODUCTION_HOST_USER#g" "$tmpfile"
    [ -n "$PRODUCTION_HOST_PORT" ] && perl -i -pe "s#\{\{PRODUCTION_HOST_PORT\}\}#$PRODUCTION_HOST_PORT#g" "$tmpfile"

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
# Docker and service management functions
# ------------------------------------------------------------------------------

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        exit_error "Docker is not running or not accessible. Please start Docker and try again."
    fi
}

# Create Docker network if it doesn't exist
ensure_docker_network() {
    local network_name="$1"
    
    if ! docker network ls | grep -q "$network_name"; then
        log_info "Creating Docker network: $network_name"
        docker network create "$network_name"
        log_success "Docker network created: $network_name"
    else
        log_info "Docker network already exists: $network_name"
    fi
}

# ------------------------------------------------------------------------------
# File permissions and security functions
# ------------------------------------------------------------------------------

# Set secure permissions for sensitive files
secure_file_permissions() {
    local file="$1"
    local permissions="${2:-600}"
    
    if [ -f "$file" ]; then
        chmod "$permissions" "$file"
        log_success "Set permissions $permissions on $file"
    else
        log_warning "File not found: $file"
    fi
}

# Create file with secure permissions
create_secure_file() {
    local file="$1"
    local permissions="${2:-600}"
    
    touch "$file"
    chmod "$permissions" "$file"
    log_success "Created secure file: $file (permissions: $permissions)"
}