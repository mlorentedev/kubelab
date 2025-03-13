#!/bin/bash
# update-env.sh - Update environment variables on the server
# Usage: ./update-env.sh <environment>
# Example: ./update-env.sh production
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "ssh"

# Check parameters
if [ "$#" -ne 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment>\nExample: $0 production"
fi

ENV=$1

# Validate environment
validate_environment "$ENV"

# Check server connectivity
check_server_connectivity "$SERVER_ALIAS"

log_info "Updating environment variables for $ENV environment..."

# Function to request input with default value
get_input() {
    local prompt=$1
    local default=$2
    local var_name=$3
    local is_secret=${4:-false}
    local is_required=${5:-false}
    
    echo -e "${YELLOW}${prompt} [${default}]: ${NC}"
    if [ "$is_secret" = true ]; then
        read -s value
        echo ""
    else
        read value
    fi
    
    if [ -z "$value" ]; then
        value="$default"
    fi
    
    if [ -z "$value" ] && [ "$is_required" = true ]; then
        log_error "This value is required."
        get_input "$prompt" "$default" "$var_name" "$is_secret" "$is_required"
        return
    fi
    
    eval "$var_name='$value'"
}

# Get current values from server
log_info "Getting current environment values from $ENV server..."
CURRENT_ENV=$(ssh "$SERVER_ALIAS" "cat $DEPLOY_DIR/.env 2>/dev/null || echo '# No file'")

# Function to extract current value from env file
get_current_value() {
    local var_name=$1
    local default=$2
    
    local value=$(echo "$CURRENT_ENV" | grep "^${var_name}=" | cut -d= -f2-)
    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Critical variables that must not be empty
validate_critical_vars() {
    local errors=0
    
    # Check critical variables
    if [ -z "$SITE_TITLE" ]; then
        log_error "SITE_TITLE cannot be empty"
        errors=$((errors+1))
    fi
    
    if [ -z "$SITE_MAIL" ]; then
        log_error "SITE_MAIL cannot be empty"
        errors=$((errors+1))
    fi
    
    if [ -z "$SITE_AUTHOR" ]; then
        log_error "SITE_AUTHOR cannot be empty"
        errors=$((errors+1))
    fi
    
    # Email configuration must be complete or all empty
    if [ -n "$EMAIL_HOST" ] || [ -n "$EMAIL_USER" ] || [ -n "$EMAIL_PASS" ]; then
        if [ -z "$EMAIL_HOST" ] || [ -z "$EMAIL_USER" ] || [ -z "$EMAIL_PASS" ]; then
            log_error "Email configuration is incomplete. All email-related fields must be filled if any are provided."
            errors=$((errors+1))
        fi
    fi
    
    # Beehiiv configuration must be complete or all empty
    if [ -n "$BEEHIIV_API_KEY" ] || [ -n "$BEEHIIV_PUB_ID" ]; then
        if [ -z "$BEEHIIV_API_KEY" ] || [ -z "$BEEHIIV_PUB_ID" ]; then
            log_error "Beehiiv configuration is incomplete. Both API key and publication ID must be provided."
            errors=$((errors+1))
        fi
    fi
    
    return $errors
}

# Extract current values or use defaults
SITE_TITLE=$(get_current_value "SITE_TITLE" "mlorente.dev")
SITE_DESCRIPTION=$(get_current_value "SITE_DESCRIPTION" "Manuel Lorente's personal blog")
SITE_MAIL=$(get_current_value "SITE_MAIL" "mlorentedev@gmail.com")
SITE_AUTHOR=$(get_current_value "SITE_AUTHOR" "Manuel Lorente")