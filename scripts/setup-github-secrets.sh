#!/bin/bash
# setup-github-secrets.sh - Configure secrets in GitHub
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Configuring GitHub secrets for CI/CD${NC}"

# Check requirements
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: GitHub CLI (gh) is not installed.${NC}"
    echo "Please install GitHub CLI: https://cli.github.com/"
    exit 1
fi

# Check authentication
if ! gh auth status &> /dev/null; then
    echo -e "${RED}Error: You are not authenticated with GitHub CLI.${NC}"
    echo "Please run 'gh auth login' first."
    exit 1
fi

# Get repository name
REPO=$(gh repo view --json nameWithOwner -q ".nameWithOwner")
if [ -z "$REPO" ]; then
    echo -e "${RED}Error: Could not determine repository.${NC}"
    echo "Make sure you're in a Git repository directory."
    exit 1
fi

echo -e "${GREEN}Configuring secrets for repository: ${REPO}${NC}"

# Function to set a secret
set_secret() {
    local name=$1
    local prompt=$2
    local default=$3
    local is_file=${4:-false}
    local is_secret=${5:-false}
    
    echo -e "${YELLOW}$prompt [${default}]: ${NC}"
    if [ "$is_file" = true ]; then
        read file_path
        if [ -z "$file_path" ]; then
            echo -e "${RED}A file is required. Operation cancelled.${NC}"
            return 1
        elif [ ! -f "$file_path" ]; then
            echo -e "${RED}File does not exist: $file_path${NC}"
            return 1
        fi
        
        # Read file content
        value=$(cat "$file_path")
    else
        if [ "$is_secret" = true ]; then
            read -s value
            echo ""
        else
            read value
        fi
        
        # Use default value if nothing was entered
        if [ -z "$value" ]; then
            value="$default"
        fi
    fi
    
    # Set secret
    if [ -n "$value" ]; then
        echo "Setting secret: $name"
        echo "$value" | gh secret set "$name" --repo "$REPO"
        echo -e "${GREEN}✓ Secret set: $name${NC}"
    else
        echo -e "${YELLOW}⚠ Secret not set: $name (empty value)${NC}"
    fi
}

# Configure DockerHub secrets
echo -e "\n${BLUE}DockerHub Configuration:${NC}"
set_secret "DOCKERHUB_USERNAME" "DockerHub username" ""
set_secret "DOCKERHUB_TOKEN" "DockerHub access token" "" false true

# Configure repository access secret
echo -e "\n${BLUE}Repository access configuration:${NC}"
set_secret "REPO_ACCESS_TOKEN" "GitHub personal access token (with 'repo' permission)" "" false true

# Configure staging server secrets
echo -e "\n${BLUE}Staging server configuration:${NC}"
set_secret "STAGING_HOST" "Host/IP of staging server" "staging.mlorente.dev"
set_secret "STAGING_USERNAME" "SSH user for staging" "deployer"
set_secret "STAGING_SSH_KEY" "Path to SSH private key file for staging" "" true

# Configure production server secrets
echo -e "\n${BLUE}Production server configuration:${NC}"
set_secret "PRODUCTION_HOST" "Host/IP of production server" "mlorente.dev"
set_secret "PRODUCTION_USERNAME" "SSH user for production" "deployer"
set_secret "PRODUCTION_SSH_KEY" "Path to SSH private key file for production" "" true

# Configure application secrets
echo -e "\n${BLUE}Application configuration:${NC}"
set_secret "SITE_TITLE" "Site title" "mlorente.dev"
set_secret "SITE_DESCRIPTION" "Site description" "Manuel Lorente's personal blog"
set_secret "SITE_AUTHOR" "Site author" "Manuel Lorente"
set_secret "SITE_MAIL" "Site email" "mlorentedev@gmail.com"
set_secret "SITE_KEYWORDS" "Site keywords" "devops, cloud, kubernetes, aws, azure, python, go"

set_secret "STAGING_SITE_DOMAIN" "Staging domain" "staging.mlorente.dev"
set_secret "STAGING_SITE_URL" "Complete staging URL" "https://staging.mlorente.dev"
set_secret "PROD_SITE_DOMAIN" "Production domain" "mlorente.dev"
set_secret "PROD_SITE_URL" "Complete production URL" "https://mlorente.dev"

# Configure social media secrets
echo -e "\n${BLUE}Social media configuration:${NC}"
set_secret "TWITTER_URL" "Twitter URL" "https://twitter.com/mlorentedev"
set_secret "YOUTUBE_URL" "YouTube URL" "https://youtube.com/@mlorentedev"
set_secret "GITHUB_URL" "GitHub URL" "https://github.com/mlorentedev"
set_secret "CALENDLY_URL" "Calendly URL" ""
set_secret "BUY_ME_A_COFFEE_URL" "Buy Me a Coffee URL" ""

# Configure integration secrets
echo -e "\n${BLUE}API configuration:${NC}"
set_secret "GOOGLE_ANALYTICS_ID" "Google Analytics ID" ""
set_secret "BEEHIIV_API_KEY" "Beehiiv API Key" "" false true
set_secret "BEEHIIV_PUB_ID" "Beehiiv Publication ID" ""

# Configure email secrets
echo -e "\n${BLUE}Email configuration:${NC}"
set_secret "EMAIL_HOST" "SMTP Host" "smtp.gmail.com"
set_secret "EMAIL_PORT" "SMTP Port" "587"
set_secret "EMAIL_SECURE" "Use secure connection? (true/false)" "false"
set_secret "EMAIL_USER" "SMTP Username (email)" ""
set_secret "EMAIL_PASS" "SMTP Password" "" false true

# Configure feature flags
echo -e "\n${BLUE}Feature flags configuration:${NC}"
set_secret "ENABLE_HOMELABS" "Enable HomeLabs? (true/false)" "true"
set_secret "ENABLE_BLOG" "Enable Blog? (true/false)" "true"
set_secret "ENABLE_CONTACT" "Enable Contact? (true/false)" "true"

echo -e "\n${GREEN}Secret configuration complete.${NC}"
echo -e "${YELLOW}All necessary secrets for CI/CD have been configured in ${REPO}.${NC}"