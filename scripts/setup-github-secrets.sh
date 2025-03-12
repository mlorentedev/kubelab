#!/bin/bash

# Script to set up GitHub Secrets using GitHub CLI
# Requirements: GitHub CLI (gh) installed and authenticated

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Configuring GitHub Secrets for mlorente.dev${NC}"
echo "This script requires GitHub CLI (gh) to be installed and authenticated."

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: GitHub CLI is not installed.${NC}"
    echo "Install from: https://cli.github.com/"
    exit 1
fi

# Check if user is authenticated with gh
if ! gh auth status &> /dev/null; then
    echo -e "${RED}Error: You are not authenticated with GitHub CLI.${NC}"
    echo "Run 'gh auth login' first."
    exit 1
fi

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q ".nameWithOwner")
if [ -z "$REPO" ]; then
    echo -e "${RED}Error: Could not determine the repository.${NC}"
    echo "Ensure you are in a Git repository directory."
    exit 1
fi

echo -e "${GREEN}Configuring secrets for repository: $REPO${NC}"

# Function to prompt and set a secret
set_secret() {
    local name=$1
    local prompt=$2
    local default=$3
    local is_file=${4:-false}
    
    echo -e "${YELLOW}$prompt${NC}"
    if [ "$is_file" = true ]; then
        read -p "File path: " value
        if [ -f "$value" ]; then
            gh secret set "$name" --repo "$REPO" --body "$(cat $value)"
            echo -e "${GREEN}✓ Secret $name set from file.${NC}"
        else
            echo -e "${RED}✗ File does not exist. Secret $name not configured.${NC}"
        fi
    else
        if [ -n "$default" ]; then
            read -p "Value [$default]: " value
            value=${value:-$default}
        else
            read -p "Value: " value
        fi
        
        if [ -n "$value" ]; then
            gh secret set "$name" --repo "$REPO" --body "$value"
            echo -e "${GREEN}✓ Secret $name configured.${NC}"
        else
            echo -e "${RED}✗ Empty value. Secret $name not configured.${NC}"
        fi
    fi
    echo ""
}

echo -e "\n${YELLOW}=== SSH Configuration ===${NC}"
source ./ssh-key-management

echo -e "\n${YELLOW}=== DockerHub Configuration ===${NC}"
set_secret "DOCKERHUB_USERNAME" "DockerHub username:"
set_secret "DOCKERHUB_TOKEN" "DockerHub access token:"

echo -e "\n${YELLOW}=== Repository Access Configuration ===${NC}"
set_secret "REPO_ACCESS_TOKEN" "Personal GitHub access token with 'repo' permission:"

echo -e "\n${YELLOW}=== Staging Server Configuration ===${NC}"
set_secret "STAGING_HOST" "Staging server host:" "staging.mlorente.dev"
set_secret "STAGING_USERNAME" "SSH username for Staging:" "deployer"
set_secret "STAGING_SSH_KEY" "Private SSH key for Staging (file path):" "" true

echo -e "\n${YELLOW}=== Production Server Configuration ===${NC}"
set_secret "PRODUCTION_HOST" "Production server host:" "mlorente.dev"
set_secret "PRODUCTION_USERNAME" "SSH username for Production:" "deployer"
set_secret "PRODUCTION_SSH_KEY" "Private SSH key for Production (file path):" "" true

echo -e "\n${YELLOW}=== Site Configuration ===${NC}"
set_secret "SITE_TITLE" "Site title:" "mlorente.dev"
set_secret "SITE_DESCRIPTION" "Site description:" "Manuel Lorente's personal blog"
set_secret "SITE_AUTHOR" "Site author:" "Manuel Lorente"
set_secret "SITE_MAIL" "Site email:" "mlorentedev@gmail.com"
set_secret "SITE_KEYWORDS" "Site keywords (comma-separated):" "devops, cloud, kubernetes, aws, azure, python, go"

set_secret "STAGING_SITE_DOMAIN" "Staging domain:" "staging.mlorente.dev"
set_secret "STAGING_SITE_URL" "Full Staging URL:" "https://staging.mlorente.dev"

set_secret "PROD_SITE_DOMAIN" "Production domain:" "mlorente.dev"
set_secret "PROD_SITE_URL" "Full Production URL:" "https://mlorente.dev"

echo -e "\n${YELLOW}=== Social Media Configuration ===${NC}"
set_secret "TWITTER_URL" "Twitter URL:" "https://twitter.com/mlorentedev"
set_secret "YOUTUBE_URL" "YouTube URL:" "https://youtube.com/@mlorentedev"
set_secret "GITHUB_URL" "GitHub URL:" "https://github.com/mlorentedev"
set_secret "CALENDLY_URL" "Calendly URL:"
set_secret "BUY_ME_A_COFFEE_URL" "Buy Me a Coffee URL:"

echo -e "\n${YELLOW}=== API Configuration ===${NC}"
set_secret "GOOGLE_ANALYTICS_ID" "Google Analytics ID:"
set_secret "BEEHIIV_API_KEY" "Beehiiv API Key:"
set_secret "BEEHIIV_PUB_ID" "Beehiiv Publication ID:"

echo -e "\n${YELLOW}=== Email Configuration ===${NC}"
set_secret "EMAIL_HOST" "SMTP Host:" "smtp.gmail.com"
set_secret "EMAIL_PORT" "SMTP Port:" "587"
set_secret "EMAIL_SECURE" "Use secure connection? (true/false):" "false"
set_secret "EMAIL_USER" "SMTP User (email):"
set_secret "EMAIL_PASS" "SMTP Password:"

echo -e "\n${YELLOW}=== Feature Flags ===${NC}"
set_secret "ENABLE_HOMELABS" "Enable HomeLabs? (true/false):" "true"
set_secret "ENABLE_BLOG" "Enable Blog? (true/false):" "true"
set_secret "ENABLE_CONTACT" "Enable Contact? (true/false):" "true"

echo -e "\n${GREEN}GitHub Secrets configuration completed.${NC}"
echo "All secrets have been configured in the repository: $REPO"