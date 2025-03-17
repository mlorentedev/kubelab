#!/bin/bash
# setup-github-secrets.sh - Configure secrets in GitHub repository
# Usage: ./setup-github-secrets.sh
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "gh"

log_info "Configuring GitHub secrets for CI/CD..."

# Check GitHub authentication
if ! gh auth status &> /dev/null; then
    exit_error "You are not authenticated with GitHub CLI. Please run 'gh auth login' first."
fi

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q ".nameWithOwner" 2>/dev/null)
if [ -z "$REPO" ]; then
    exit_error "Could not determine repository. Make sure you're in a Git repository directory."
fi

log_success "Configuring secrets for repository: $REPO"

# Function to set a secret
set_secret() {
    local name=$1
    local prompt=$2
    local default=$3
    local is_file=${4:-false}
    local is_secret=${5:-false}
    local is_required=${6:-false}
    
    log_info "$prompt"
    if [ "$is_file" = true ]; then
        echo -e "${YELLOW}File path:${NC} "
        read file_path
        
        if [ -z "$file_path" ] && [ "$is_required" = true ]; then
            log_error "A file is required. Please provide a valid file path."
            set_secret "$name" "$prompt" "$default" "$is_file" "$is_secret" "$is_required"
            return
        elif [ -z "$file_path" ]; then
            log_warning "Empty file path. Secret $name will not be set."
            return
        elif [ ! -f "$file_path" ]; then
            log_error "File does not exist: $file_path"
            set_secret "$name" "$prompt" "$default" "$is_file" "$is_secret" "$is_required"
            return
        fi
        
        # Read file content
        value=$(cat "$file_path")
    else
        if [ "$is_secret" = true ]; then
            echo -e "${YELLOW}Value [******]:${NC} "
            read -s value
            echo ""
        else
            echo -e "${YELLOW}Value [$default]:${NC} "
            read value
        fi
        
        # Use default value if nothing was entered
        if [ -z "$value" ]; then
            value="$default"
        fi
        
        if [ -z "$value" ] && [ "$is_required" = true ]; then
            log_error "This value is required."
            set_secret "$name" "$prompt" "$default" "$is_file" "$is_secret" "$is_required"
            return
        fi
    fi
    
    # Set secret
    if [ -n "$value" ]; then
        echo "$value" | gh secret set "$name" --repo "$REPO"
        log_success "Secret set: $name"
    else
        log_warning "Secret not set: $name (empty value)"
    fi
}

# Confirm before starting
if ! confirm_action "This will configure GitHub secrets for CI/CD in $REPO. Continue?"; then
    exit 0
fi

# Configure DockerHub secrets
log_info "DockerHub Configuration:"
set_secret "DOCKERHUB_USERNAME" "DockerHub username" "" false false true
set_secret "DOCKERHUB_TOKEN" "DockerHub access token" "" false true true

# Configure repository access secret
log_info "Repository access configuration:"
set_secret "REPO_ACCESS_TOKEN" "GitHub personal access token (with 'repo' permission)" "" false true true

# Prepare SSH key for deployment
log_info "Setting up SSH key for deployment..."
ensure_ssh_key

# Configure staging server secrets
log_info "Staging server configuration:"
set_secret "STAGING_HOST" "Host/IP of staging server" "staging.mlorente.dev" false false true
set_secret "STAGING_USERNAME" "SSH user for staging" "deployer" false false true
set_secret "SSH_PRIVATE_KEY" "Using detected SSH private key" "" false false false
cat "$SSH_KEY_PATH" | gh secret set "SSH_PRIVATE_KEY" --repo "$REPO"
cat "${SSH_KEY_PATH}.pub" | gh secret set "SSH_PUBLIC_KEY" --repo "$REPO"
log_success "SSH key secrets set"

# Configure production server secrets
log_info "Production server configuration:"
set_secret "PRODUCTION_HOST" "Host/IP of production server" "mlorente.dev" false false true
set_secret "PRODUCTION_USERNAME" "SSH user for production" "deployer" false false true

# Configure application secrets
log_info "Application configuration:"
set_secret "SITE_TITLE" "Site title" "mlorente.dev" false false true
set_secret "SITE_DESCRIPTION" "Site description" "Manuel Lorente's personal blog"
set_secret "SITE_AUTHOR" "Site author" "Manuel Lorente" false false true
set_secret "SITE_MAIL" "Site email" "mlorentedev@gmail.com" false false true
set_secret "SITE_KEYWORDS" "Site keywords" "devops, cloud, kubernetes, aws, azure, python, go"

set_secret "STAGING_SITE_DOMAIN" "Staging domain" "staging.mlorente.dev" false false true
set_secret "STAGING_SITE_URL" "Complete staging URL" "https://staging.mlorente.dev" false false true
set_secret "PROD_SITE_DOMAIN" "Production domain" "mlorente.dev" false false true
set_secret "PROD_SITE_URL" "Complete production URL" "https://mlorente.dev" false false true

# Configure social media secrets
log_info "Social media configuration:"
set_secret "TWITTER_URL" "Twitter URL" "https://twitter.com/mlorentedev"
set_secret "YOUTUBE_URL" "YouTube URL" "https://youtube.com/@mlorentedev"
set_secret "GITHUB_URL" "GitHub URL" "https://github.com/mlorentedev"
set_secret "CALENDLY_URL" "Calendly URL" ""

# Configure integration secrets
log_info "API configuration:"
set_secret "GOOGLE_ANALYTICS_ID" "Google Analytics ID" ""
set_secret "BEEHIIV_API_KEY" "Beehiiv API Key" "" false true
set_secret "BEEHIIV_PUB_ID" "Beehiiv Publication ID" ""

# Configure email secrets
log_info "Email configuration:"
set_secret "EMAIL_HOST" "SMTP Host" "smtp.gmail.com"
set_secret "EMAIL_PORT" "SMTP Port" "587"
set_secret "EMAIL_SECURE" "Use secure connection? (true/false)" "false"
set_secret "EMAIL_USER" "SMTP Username (email)" ""
set_secret "EMAIL_PASS" "SMTP Password" "" false true

# Configure feature flags
log_info "Feature flags configuration:"
set_secret "ENABLE_HOMELABS" "Enable HomeLabs? (true/false)" "true"
set_secret "ENABLE_BLOG" "Enable Blog? (true/false)" "true"
set_secret "ENABLE_CONTACT" "Enable Contact? (true/false)" "true"

log_success "Secret configuration completed successfully!"
log_info "All necessary secrets for CI/CD have been configured in $REPO."