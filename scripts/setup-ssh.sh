#!/bin/bash

# Comprehensive SSH Key Management Script for mlorente.dev

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration variables
KEY_TYPE="ed25519"
KEY_COMMENT="mlorente-deployment"
SSH_DIR="$HOME/.ssh"
KEY_PATH="$SSH_DIR/id_${KEY_TYPE}_mlorente"

# Logging function
log() {
    local type="$1"
    local message="$2"
    local color=""

    case "$type" in
        "info")    color=$BLUE ;;
        "success") color=$GREEN ;;
        "warning") color=$YELLOW ;;
        "error")   color=$RED ;;
        *)         color=$NC ;;
    esac

    echo -e "${color}[${type^^}]${NC} $message"
}

# Check dependencies
check_dependencies() {
    local deps=("ssh-keygen" "ssh-copy-id" "gh")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            log "error" "$dep is not installed"
            exit 1
        fi
    done
}

# Generate SSH key
generate_ssh_key() {
    log "info" "Generating SSH key for deployment"
    
    # Check if key already exists
    if [[ -f "$KEY_PATH" ]]; then
        read -p "SSH key already exists. Overwrite? (y/n): " overwrite
        if [[ "$overwrite" != "y" ]]; then
            log "warning" "Key generation cancelled"
            return 1
        fi
    fi

    # Generate the key
    ssh-keygen -t "$KEY_TYPE" -f "$KEY_PATH" -C "$KEY_COMMENT"
    
    if [[ $? -eq 0 ]]; then
        log "success" "SSH key generated successfully"
        # Set correct permissions
        chmod 600 "$KEY_PATH"
        chmod 644 "${KEY_PATH}.pub"
    else
        log "error" "Failed to generate SSH key"
        return 1
    fi
}

# Add SSH key to server
add_key_to_server() {
    local server_ip="$1"
    local username="${2:-deployer}"

    if [[ -z "$server_ip" ]]; then
        read -p "Enter server IP: " server_ip
    fi

    log "info" "Adding SSH key to server $server_ip for user $username"
    
    # Copy SSH key to server
    ssh-copy-id -i "$KEY_PATH.pub" "${username}@${server_ip}"
    
    if [[ $? -eq 0 ]]; then
        log "success" "SSH key added to server successfully"
    else
        log "error" "Failed to add SSH key to server"
        return 1
    fi
}

# Configure GitHub secrets
configure_github_secrets() {
    log "info" "Configuring GitHub secrets"

    # Check GitHub CLI authentication
    if ! gh auth status &> /dev/null; then
        log "error" "Not authenticated with GitHub CLI. Run 'gh auth login' first."
        return 1
    fi

    # Get repository
    local repo
    repo=$(gh repo view --json nameWithOwner -q ".nameWithOwner")

    if [[ -z "$repo" ]]; then
        log "error" "Could not determine repository"
        return 1
    fi

    # Read public and private keys
    local public_key
    local private_key
    public_key=$(cat "${KEY_PATH}.pub")
    private_key=$(cat "$KEY_PATH")

    # Set SSH secrets
    echo "$public_key" | gh secret set "SSH_PUBLIC_KEY" --repo "$repo"
    echo "$private_key" | gh secret set "SSH_PRIVATE_KEY" --repo "$repo"

    log "success" "GitHub secrets configured for $repo"
}

# SSH config file generator
generate_ssh_config() {
    local config_file="$SSH_DIR/config"
    
    log "info" "Generating SSH config file"
    
    cat > "$config_file" <<EOL
# SSH Configuration for mlorente.dev deployments

# Staging Server
Host mlorente-staging
    HostName staging.mlorente.dev
    User deployer
    IdentityFile $KEY_PATH

# Production Server
Host mlorente-prod
    HostName mlorente.dev
    User deployer
    IdentityFile $KEY_PATH
EOL

    chmod 600 "$config_file"
    log "success" "SSH config file created at $config_file"
}

# Main menu
main_menu() {
    check_dependencies

    PS3="Select an action: "
    options=("Generate SSH Key" 
             "Add Key to Server" 
             "Configure GitHub Secrets" 
             "Generate SSH Config" 
             "All Steps" 
             "Exit")
    
    select opt in "${options[@]}"; do
        case $opt in
            "Generate SSH Key")
                generate_ssh_key
                ;;
            "Add Key to Server")
                add_key_to_server
                ;;
            "Configure GitHub Secrets")
                configure_github_secrets
                ;;
            "Generate SSH Config")
                generate_ssh_config
                ;;
            "All Steps")
                generate_ssh_key && 
                add_key_to_server && 
                configure_github_secrets && 
                generate_ssh_config
                ;;
            "Exit")
                break
                ;;
            *) 
                log "warning" "Invalid option $REPLY"
                ;;
        esac
    done
}

# Run main menu
main_menu