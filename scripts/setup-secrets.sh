#!/bin/bash
# setup-github-secrets.sh - Configure secrets in GitHub repository
# Usage: ./setup-github-secrets.sh
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "gh"

# Check if .env file exists
ENV_FILE="$(dirname "$0")/../.env"
if [ ! -f "$ENV_FILE" ]; then
    log_error "No .env file found. Please create a .env file first."
    exit 1
fi
log_info "Loading environment variables from $ENV_FILE..."
export $(grep -v '^#' "$ENV_FILE" | xargs)

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

# Loop through all variables in the .env file and set them as GitHub secrets
while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and empty lines
    if [[ "$line" =~ ^#.*$ || -z "$line" ]]; then
        continue
    fi

    # Split key and value
    IFS='=' read -r key value <<< "$line"

    # Trim leading/trailing whitespace (Bash 4+)
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)

    # Remove surrounding quotes from value if present
    value="${value%\"}"
    value="${value#\"}"

    # Set secret in GitHub
    echo "$value" | gh secret set "$key" --repo "$REPO"
    log_success "Secret set: $key"
done < "$ENV_FILE"

log_info "Secret configuration completed successfully in $REPO."
