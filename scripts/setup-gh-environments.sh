#!/bin/bash
# Script to create GitHub environments for CD Pipeline
# Requires GitHub CLI (gh) installed and authenticated

# Ensure GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "GitHub CLI is not installed. Please install it first:"
    echo "https://cli.github.com/manual/installation"
    exit 1
fi

# Verify that the user is authenticated
if ! gh auth status &> /dev/null; then
    echo "You are not authenticated with GitHub CLI. Please run 'gh auth login'"
    exit 1
fi

# Get the current repository name
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
if [ -z "$REPO" ]; then
    echo "Could not determine the current repository."
    echo "Please run this script within a Git repository."
    exit 1
fi

echo "Creating environments for repository: $REPO"

# Create staging environment
echo "Creating 'staging' environment..."
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$REPO/environments/staging"

# Create production environment with protection rules
echo "Creating 'production' environment with protection rules..."
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$REPO/environments/production" \
  -f wait_timer=1 \
  -f reviewers='[{"type": "User", "id": '"$(gh api /user --jq '.id')"'}]'

echo "Environments created successfully."
echo "Note: To configure additional rules, visit the repository settings in GitHub."