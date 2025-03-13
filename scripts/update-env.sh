#!/bin/bash
# update-env.sh - Update environment variables on the server
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -ne 1 ]; then
    echo -e "${RED}Error: Missing environment.${NC}"
    echo "Usage: $0 <environment>"
    echo "Example: $0 production"
    exit 1
fi

ENV=$1

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Configure variables based on environment
if [ "$ENV" == "production" ]; then
    SERVER="mlorente-production"
    DEPLOY_DIR="/opt/mlorente"
    DOMAIN="mlorente.dev"
    SITE_URL="https://mlorente.dev"
else
    SERVER="mlorente-staging"
    DEPLOY_DIR="/opt/mlorente-staging"
    DOMAIN="staging.mlorente.dev"
    SITE_URL="https://staging.mlorente.dev"
fi

# Check if we can connect to the server
if ! ssh -q $SERVER exit; then
    echo -e "${RED}Error: Cannot connect to server ${SERVER}.${NC}"
    echo "Verify that the server is correctly configured."
    exit 1
fi

# Request values for environment variables
echo -e "${BLUE}Updating environment variables for ${ENV}...${NC}"
echo -e "${YELLOW}Leave blank to keep current value.${NC}"

# Function to request input with default value
get_input() {
    local prompt=$1
    local default=$2
    local var_name=$3
    local is_secret=${4:-false}
    
    echo -e "${YELLOW}${prompt} [${default}]: ${NC}"
    if [ "$is_secret" = true ]; then
        read -s value
        echo ""
    else
        read value
    fi
    
    if [ -z "$value" ]; then
        value=$default
    fi
    
    eval "$var_name='$value'"
}

# Get current values
echo -e "${BLUE}Getting current values...${NC}"
CURRENT_ENV=$(ssh $SERVER "cat ${DEPLOY_DIR}/.env || echo '# No file'")

# Extract current values or use defaults
get_current_value() {
    local var_name=$1
    local default=$2
    
    local value=$(echo "$CURRENT_ENV" | grep "^${var_name}=" | cut -d= -f2-)
    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# Application variables
SITE_TITLE=$(get_current_value "SITE_TITLE" "mlorente.dev")
SITE_DESCRIPTION=$(get_current_value "SITE_DESCRIPTION" "Manuel Lorente's personal blog")
SITE_MAIL=$(get_current_value "SITE_MAIL" "mlorentedev@gmail.com")
SITE_AUTHOR=$(get_current_value "SITE_AUTHOR" "Manuel Lorente")
SITE_KEYWORDS=$(get_current_value "SITE_KEYWORDS" "devops, cloud, kubernetes, aws, azure, python, go")

# Social media
TWITTER_URL=$(get_current_value "TWITTER_URL" "https://twitter.com/mlorentedev")
YOUTUBE_URL=$(get_current_value "YOUTUBE_URL" "https://youtube.com/@mlorentedev")
GITHUB_URL=$(get_current_value "GITHUB_URL" "https://github.com/mlorentedev")
CALENDLY_URL=$(get_current_value "CALENDLY_URL" "")
BUY_ME_A_COFFEE_URL=$(get_current_value "BUY_ME_A_COFFEE_URL" "")

# Integrations
GOOGLE_ANALYTICS_ID=$(get_current_value "GOOGLE_ANALYTICS_ID" "")
BEEHIIV_API_KEY=$(get_current_value "BEEHIIV_API_KEY" "")
BEEHIIV_PUB_ID=$(get_current_value "BEEHIIV_PUB_ID" "")

# Email
EMAIL_HOST=$(get_current_value "EMAIL_HOST" "smtp.gmail.com")
EMAIL_PORT=$(get_current_value "EMAIL_PORT" "587")
EMAIL_SECURE=$(get_current_value "EMAIL_SECURE" "false")
EMAIL_USER=$(get_current_value "EMAIL_USER" "")
EMAIL_PASS=$(get_current_value "EMAIL_PASS" "")

# Flags
ENABLE_HOMELABS=$(get_current_value "ENABLE_HOMELABS" "true")
ENABLE_BLOG=$(get_current_value "ENABLE_BLOG" "true")
ENABLE_CONTACT=$(get_current_value "ENABLE_CONTACT" "true")

# Request new values
echo -e "\n${BLUE}Site information:${NC}"
get_input "Site title" "$SITE_TITLE" "SITE_TITLE"
get_input "Site description" "$SITE_DESCRIPTION" "SITE_DESCRIPTION"
get_input "Site email" "$SITE_MAIL" "SITE_MAIL"
get_input "Site author" "$SITE_AUTHOR" "SITE_AUTHOR"
get_input "Keywords (comma-separated)" "$SITE_KEYWORDS" "SITE_KEYWORDS"

echo -e "\n${BLUE}Social media:${NC}"
get_input "Twitter URL" "$TWITTER_URL" "TWITTER_URL"
get_input "YouTube URL" "$YOUTUBE_URL" "YOUTUBE_URL"
get_input "GitHub URL" "$GITHUB_URL" "GITHUB_URL"
get_input "Calendly URL" "$CALENDLY_URL" "CALENDLY_URL"
get_input "Buy Me a Coffee URL" "$BUY_ME_A_COFFEE_URL" "BUY_ME_A_COFFEE_URL"

echo -e "\n${BLUE}Integrations:${NC}"
get_input "Google Analytics ID" "$GOOGLE_ANALYTICS_ID" "GOOGLE_ANALYTICS_ID"
get_input "Beehiiv API Key" "$BEEHIIV_API_KEY" "BEEHIIV_API_KEY" true
get_input "Beehiiv Publication ID" "$BEEHIIV_PUB_ID" "BEEHIIV_PUB_ID" true

echo -e "\n${BLUE}Email configuration:${NC}"
get_input "SMTP Host" "$EMAIL_HOST" "EMAIL_HOST"
get_input "SMTP Port" "$EMAIL_PORT" "EMAIL_PORT"
get_input "Use secure connection? (true/false)" "$EMAIL_SECURE" "EMAIL_SECURE"
get_input "SMTP Username" "$EMAIL_USER" "EMAIL_USER"
get_input "SMTP Password" "$EMAIL_PASS" "EMAIL_PASS" true

echo -e "\n${BLUE}Feature flags:${NC}"
get_input "Enable HomeLabs? (true/false)" "$ENABLE_HOMELABS" "ENABLE_HOMELABS"
get_input "Enable Blog? (true/false)" "$ENABLE_BLOG" "ENABLE_BLOG"
get_input "Enable Contact? (true/false)" "$ENABLE_CONTACT" "ENABLE_CONTACT"

# Generate new .env file
ENV_CONTENT=$(cat <<EOF
# Environment: ${ENV}
# Generated on: $(date)
# WARNING: This file is generated by update-env.sh

# Common settings
ENV=${ENV}

# Application settings
SITE_URL=${SITE_URL}
SITE_TITLE=${SITE_TITLE}
SITE_DESCRIPTION=${SITE_DESCRIPTION}
SITE_DOMAIN=${DOMAIN}
SITE_MAIL=${SITE_MAIL}
SITE_AUTHOR=${SITE_AUTHOR}
SITE_KEYWORDS=${SITE_KEYWORDS}

# Social media
TWITTER_URL=${TWITTER_URL}
YOUTUBE_URL=${YOUTUBE_URL}
GITHUB_URL=${GITHUB_URL}
CALENDLY_URL=${CALENDLY_URL}
BUY_ME_A_COFFEE_URL=${BUY_ME_A_COFFEE_URL}

# Analytics
GOOGLE_ANALYTICS_ID=${GOOGLE_ANALYTICS_ID}

# Feature flags
ENABLE_HOMELABS=${ENABLE_HOMELABS}
ENABLE_BLOG=${ENABLE_BLOG}
ENABLE_CONTACT=${ENABLE_CONTACT}

# API credentials
BEEHIIV_API_KEY=${BEEHIIV_API_KEY}
BEEHIIV_PUB_ID=${BEEHIIV_PUB_ID}

# Email settings
EMAIL_HOST=${EMAIL_HOST}
EMAIL_PORT=${EMAIL_PORT}
EMAIL_SECURE=${EMAIL_SECURE}
EMAIL_USER=${EMAIL_USER}
EMAIL_PASS=${EMAIL_PASS}

# Backend URL for frontend
BACKEND_URL=http://backend:8080
EOF
)

# Confirm changes
echo -e "\n${YELLOW}New environment variables for ${ENV}:${NC}"
echo "$ENV_CONTENT" | grep -v "API_KEY\|PASS=" | grep -v "^#"

echo -e "\n${YELLOW}Confirm these changes? (y/n)${NC}"
read confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo -e "${RED}Changes cancelled.${NC}"
    exit 0
fi

# Update .env file on the server
echo -e "${BLUE}Updating .env file on the server...${NC}"
ssh $SERVER "mkdir -p ${DEPLOY_DIR}/backups"
ssh $SERVER "cp ${DEPLOY_DIR}/.env ${DEPLOY_DIR}/backups/.env.$(date +%Y%m%d%H%M%S) 2>/dev/null || true"
echo "$ENV_CONTENT" | ssh $SERVER "cat > ${DEPLOY_DIR}/.env"

# Restart services
echo -e "${BLUE}Restarting services...${NC}"
ssh $SERVER "cd ${DEPLOY_DIR} && docker-compose up -d"

echo -e "${GREEN}Environment variables updated successfully.${NC}"