#!/bin/bash
# setup-github-secrets.sh - Configure secrets in GitHub repository from multiple .env files
# Usage: ./setup-github-secrets.sh [ENV_PATH]
# If ENV_PATH is not provided, it will use default locations
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "gh"

# Define environment files to process based on input parameter
if [ -n "$1" ]; then
    # User provided a custom .env path
    ENV_BASE_PATH="$1"
    ENV_FILES=("$ENV_BASE_PATH")
    log_info "Using custom environment file: $ENV_BASE_PATH"
else
    # Use default paths
    ENV_FILES=(
        "$(dirname "$0")/.env"
    )
    log_info "Using default environment file paths"
fi

# Function to set a GitHub secret
set_secret() {
    local name="$1" 
    local value="$2"

    # Validate inputs
    if [ -z "$name" ]; then
        log_error "Secret name cannot be empty."
        return 1
    fi
    
    # Validate secret value
    if ! validate_secret_value "$name" "$value"; then
        log_error "Validation failed for secret '$name'. Skipping."
        return 1
    fi
    
    # Log debug info
    log_info "Setting secret '$name' (length: ${#value} chars, first 3: ${value:0:3}...)"
    
    # Wait a random time between 0.000 and 0.500 seconds to avoid rate limiting
    sleep_time=$(bc -l <<< "scale=3; $RANDOM/32767/2")
    sleep "$sleep_time"

    # Remove any existing secret with the same name
    gh secret delete "$name" --repo "$REPO" -y 2>/dev/null || true

    # Set the new secret
    if echo -n "$value" | gh secret set "$name" --repo "$REPO" -b -; then
        log_success "✅ Secret '$name' set successfully"
    else
        log_error "❌ Failed to set secret '$name'"
        return 1
    fi
}

validate_secret_value() {
    local key="$1"
    local value="$2"
    
    # Check if value is empty
    if [ -z "$value" ]; then
        log_error "Secret '$key' has empty value. Skipping."
        return 1
    fi
    
    # Check if value is just whitespace
    if [[ "$value" =~ ^[[:space:]]*$ ]]; then
        log_error "Secret '$key' contains only whitespace. Skipping."
        return 1
    fi
    
    # Check if value is just a single dash
    if [ "$value" = "-" ]; then
        log_error "Secret '$key' has invalid value '-'. Skipping."
        return 1
    fi
    
    # Check if value is suspiciously short (less than 3 characters)
    if [ ${#value} -lt 3 ]; then
        log_warning "Secret '$key' has very short value (${#value} chars): '$value'. Continue? (y/N)"
        read -r confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            log_info "Skipping secret '$key'"
            return 1
        fi
    fi
    
    # Specific validations for known secrets
    case "$key" in
        DOCKERHUB_USERNAME)
            # Docker usernames should be alphanumeric with some allowed chars
            if [[ ! "$value" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
                log_error "Invalid Docker username format: '$value'. Should be alphanumeric with ._- allowed."
                return 1
            fi
            if [ ${#value} -lt 3 ] || [ ${#value} -gt 30 ]; then
                log_error "Docker username length invalid: ${#value} chars. Should be 3-30 chars."
                return 1
            fi
            ;;
        DOCKERHUB_TOKEN)
            # Docker tokens should start with dckr_pat_
            if [[ ! "$value" =~ ^dckr_pat_ ]]; then
                log_error "Invalid Docker token format: should start with 'dckr_pat_'"
                return 1
            fi
            if [ ${#value} -lt 30 ]; then
                log_error "Docker token too short: ${#value} chars. Should be ~40+ chars."
                return 1
            fi
            ;;
        *TOKEN*|*KEY*|*SECRET*)
            # Generic token/key validation
            if [ ${#value} -lt 8 ]; then
                log_warning "Token/key '$key' seems short (${#value} chars). Continue? (y/N)"
                read -r confirm
                if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
                    return 1
                fi
            fi
            ;;
        *EMAIL*)
            # Basic email validation
            if [[ ! "$value" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
                log_error "Invalid email format: '$value'"
                return 1
            fi
            ;;
        *URL*)
            # Basic URL validation
            if [[ ! "$value" =~ ^https?:// ]]; then
                log_error "Invalid URL format: '$value'. Should start with http:// or https://"
                return 1
            fi
            ;;
    esac
    
    return 0
}

process_env_line() {
    local line="$1"
    
    # Skip comments, empty lines, and lines without '='
    if [[ "$line" =~ ^[[:space:]]*#.*$ ]] || [[ -z "$line" ]] || [[ ! "$line" =~ = ]]; then
        return 0
    fi
    
    # More robust key=value parsing
    local key="${line%%=*}"
    local value="${line#*=}"
    
    # Trim whitespace without using xargs (which can truncate)
    key="${key#"${key%%[![:space:]]*}"}"   # Remove leading whitespace
    key="${key%"${key##*[![:space:]]}"}"   # Remove trailing whitespace
    value="${value#"${value%%[![:space:]]*}"}"   # Remove leading whitespace  
    value="${value%"${value##*[![:space:]]}"}"   # Remove trailing whitespace
    
    # Remove surrounding quotes
    if [[ "$value" =~ ^\".*\"$ ]]; then
        value="${value#\"}"
        value="${value%\"}"
    elif [[ "$value" =~ ^\'.*\'$ ]]; then
        value="${value#\'}"
        value="${value%\'}"
    fi
    
    # Debug: show what we parsed
    log_info "Parsed: key='$key', value_length=${#value}, value_preview='${value:0:10}...'"
    
    # Validate key name
    if [[ ! "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]]; then
        log_warning "Invalid secret name format: '$key'. Should be UPPERCASE_WITH_UNDERSCORES."
        return 1
    fi
    
    return 0
}

# Function to process env files and set GitHub secrets
process_env_files() {
    local processed_secrets=()

    for env_file in "${ENV_FILES[@]}"; do
        if [ ! -f "$env_file" ]; then
            log_warning "Environment file not found: $env_file"
            continue
        fi

        log_info "Processing environment file: $env_file"

        # Read and process each line in the env file
        while IFS= read -r line || [ -n "$line" ]; do
            # Skip comments, empty lines, and lines without '='
            if [[ "$line" =~ ^[[:space:]]*#.*$ ]] || [[ -z "$line" ]] || [[ ! "$line" =~ = ]]; then
                continue
            fi
            
            # More robust key=value parsing
            local key="${line%%=*}"
            local value="${line#*=}"
            
            # Process with validation (from artifact)
            if process_env_line "$line"; then
                # Skip already processed secrets to avoid duplicates
                if [[ " ${processed_secrets[*]} " =~ " $key " ]]; then
                    log_warning "Skipping duplicate secret: $key"
                    continue
                fi
                
                # Add to processed secrets
                processed_secrets+=("$key")
                
                # Handle special cases for SSH keys
                if [[ $key == *SSH_PRIVATE_KEY_BASE64* ]]; then
                    new_key=${key/_BASE64/}
                    log_info "Decoding SSH key for: $new_key"
                    tmp=$(mktemp)
                    echo "$value" | base64 -d > "$tmp"
                    chmod 600 "$tmp"
                    set_secret "$new_key" "$(cat "$tmp")"
                    rm -f "$tmp"
                    continue
                fi           
                
                set_secret "$key" "$value"
            fi
        done < "$env_file"
    done
}

# Check GitHub authentication
if ! gh auth status &> /dev/null; then
    exit_error "You are not authenticated with GitHub CLI. Please run 'gh auth login' first."
fi

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q ".nameWithOwner" 2>/dev/null)
if [ -z "$REPO" ]; then
    exit_error "Could not determine repository. Make sure you're in a Git repository directory."
fi

log_info "Configuring secrets for repository: $REPO"

# Process environment files and set GitHub secrets
process_env_files

# Show information about the SSH key configuration
log_info "SSH Key Configuration:"
log_info "1. If you provided SSH_PRIVATE_KEY_BASE64, it's been decoded and set as SSH_PRIVATE_KEY"
log_info "2. Make sure the corresponding public key is added to your server's authorized_keys"
log_info "3. Use the SSH_PRIVATE_KEY in your GitHub Actions workflows"