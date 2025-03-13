#!/bin/bash
# utils.sh - Common utilities for mlorente.dev scripts
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

# Validate environment parameter
validate_environment() {
    local env=$1
    
    if [[ -z "$env" ]]; then
        exit_error "Missing environment parameter."
    fi
    
    if [[ "$env" != "production" && "$env" != "staging" ]]; then
        exit_error "Environment must be 'production' or 'staging'."
    fi
    
    # Configure variables based on environment
    if [ "$env" == "production" ]; then
        export SERVER_ALIAS="mlorente-prod"
        export SERVER_HOST="mlorente.dev"
        export DEPLOY_DIR="/opt/mlorente"
        export DOMAIN="mlorente.dev"
        export SITE_URL="https://mlorente.dev"
        export BRANCH="master"
    else # staging
        export SERVER_ALIAS="mlorente-staging"
        export SERVER_HOST="staging.mlorente.dev"
        export DEPLOY_DIR="/opt/mlorente-staging"
        export DOMAIN="staging.mlorente.dev"
        export SITE_URL="https://staging.mlorente.dev"
        export BRANCH="develop"
    fi
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
# SSH key functions
# ------------------------------------------------------------------------------

# Generate SSH key if it doesn't exist
ensure_ssh_key() {
    local key_path=${1:-"$HOME/.ssh/id_rsa_mlorente"}
    local comment=${2:-"mlorente-deployment"}
    
    if [ ! -f "$key_path" ]; then
        log_info "SSH key not found at $key_path"
        if confirm_action "Do you want to generate a new SSH key?"; then
            log_info "Generating new SSH key..."
            
            # Ensure the .ssh directory exists
            mkdir -p "$(dirname "$key_path")"
            
            # Generate the key
            ssh-keygen -t rsa -b 4096 -f "$key_path" -C "$comment" -N ""
            
            # Set correct permissions
            chmod 600 "$key_path"
            chmod 644 "${key_path}.pub"
            
            log_success "SSH key generated: $key_path"
        else
            exit_error "SSH key is required for deployment."
        fi
    else
        log_info "Using existing SSH key: $key_path"
    fi
    
    # Display the public key
    log_info "Public key (you may need to copy this):"
    cat "${key_path}.pub"
    
    export SSH_KEY_PATH="$key_path"
}