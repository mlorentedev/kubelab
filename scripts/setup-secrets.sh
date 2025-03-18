#!/bin/bash
# setup-github-secrets.sh - Configure secrets in GitHub repository from multiple .env files
# Usage: ./setup-github-secrets.sh
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "gh"

# Define environment files to process
ENV_FILES=(
    "$(dirname "$0")/../.env"
    "$(dirname "$0")/../.env.backend.development"
    "$(dirname "$0")/../.env.frontend.development"
)

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
            if [[ "$line" =~ ^#.*$ || -z "$line" || ! "$line" =~ = ]]; then
                continue
            fi

            # Split key and value
            IFS='=' read -r key value <<< "$line"

            # Trim leading/trailing whitespace
            key=$(echo "$key" | xargs)
            value=$(echo "$value" | xargs)

            # Remove surrounding quotes from value if present
            value="${value%\"}"
            value="${value#\"}"

            # Skip already processed secrets to avoid duplicates
            if [[ " ${processed_secrets[*]} " =~ " $key " ]]; then
                log_warning "Skipping duplicate secret: $key"
                continue
            fi

            # Prefix environment-specific variables to avoid conflicts
            if [[ "$env_file" == *"backend"* ]]; then
                prefixed_key="BACKEND_${key}"
            elif [[ "$env_file" == *"frontend"* ]]; then
                prefixed_key="FRONTEND_${key}"
            else
                prefixed_key="$key"
            fi

            # Add to processed secrets to prevent duplicates
            processed_secrets+=("$key")

            # Mask potentially sensitive values
            masked_value=$(echo "$value" | sed 's/./*/g')
            log_info "Setting secret: $prefixed_key (value masked: $masked_value)"

            # Set GitHub secret
            echo "$value" | gh secret set "$prefixed_key" --repo "$REPO"
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

log_success "Configuring secrets for repository: $REPO"

# Process environment files and set GitHub secrets
process_env_files

# Optional: Add specific environment-specific configuration
log_info "Configuring deployment environments..."

# Set deployment environment flags
gh secret set "DEPLOY_STAGING_ENABLED" --repo "$REPO" <<< "true"
gh secret set "DEPLOY_PRODUCTION_ENABLED" --repo "$REPO" <<< "true"

# Additional configuration for CI/CD
gh secret set "CI_CD_BRANCH_PROTECTION" --repo "$REPO" <<< "true"

log_success "Secret configuration completed successfully in $REPO."

# Optional: Verify secrets configuration
log_info "Verifying GitHub secrets configuration..."
gh secret list --repo "$REPO"