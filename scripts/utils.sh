#!/bin/zsh
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
            if grep -q "MAIN_AUTHENTICATION_CREDENTIALS=" "$env_file"; then
                # Replace existing line - using single quotes to prevent $ expansion
                sed -i "s|MAIN_AUTHENTICATION_CREDENTIALS=.*|MAIN_AUTHENTICATION_CREDENTIALS='$credentials'|" "$env_file"
                log_success "Updated credentials in $env_file"
            else
                # Add new line - using single quotes to prevent $ expansion
                echo "MAIN_AUTHENTICATION_CREDENTIALS='$credentials'" >> "$env_file"
                log_success "Added credentials to $env_file"
            fi
        else
            log_warning "File $env_file doesn't exist, skipping."
        fi
    done
}

# Update credentials (user + password) in .env files with configurable variable names
update_separate_credentials() {
    local username="$1"            # value for user
    local password="$2"            # value for password
    local user_var="$3"            # env var name for username
    local pass_var="$4"            # env var name for password
    shift 4
    local env_files=("$@")

    if [ ${#env_files[@]} -eq 0 ]; then
        log_error "No environment files specified"
        return 1
    fi

    for env_file in "${env_files[@]}"; do
        if [ -f "$env_file" ]; then
            # Update user variable
            if grep -q "^${user_var}=" "$env_file"; then
                sed -i "s|^${user_var}=.*|${user_var}='${username}'|" "$env_file"
            else
                echo "${user_var}='${username}'" >> "$env_file"
            fi

            # Update password variable
            if grep -q "^${pass_var}=" "$env_file"; then
                sed -i "s|^${pass_var}=.*|${pass_var}='${password}'|" "$env_file"
            else
                echo "${pass_var}='${password}'" >> "$env_file"
            fi

            log_success "Updated credentials in $env_file"
        else
            log_warning "File $env_file doesn't exist, skipping."
        fi
    done
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