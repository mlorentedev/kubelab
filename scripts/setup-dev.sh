#!/bin/bash
# dev-setup.sh - Setup development environment
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Setting up development environment for mlorente.dev${NC}"

# Check requirements
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed. Please install it first.${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: Docker Compose is not installed. Please install it first.${NC}"
    exit 1
fi

# Create .env.development file if it doesn't exist
if [ ! -f ".env.development" ]; then
    echo -e "${YELLOW}Creating .env.development file...${NC}"
    cat > .env.development <<EOL
# Environment Variables - Development
ENV=development
VERSION=1.0.0

# Application
PUBLIC_SITE_TITLE=mlorente.dev
PUBLIC_SITE_DESCRIPTION=mlorentedev site
PUBLIC_SITE_DOMAIN=localhost
PUBLIC_SITE_URL=http://localhost:3000
PUBLIC_SITE_MAIL=mlorentedev@gmail.com
PUBLIC_SITE_AUTHOR=Manuel Lorente
PUBLIC_SITE_KEYWORDS=devops, cloud, kubernetes, aws, azure, python, go

# Social media
PUBLIC_BUY_ME_A_COFFEE_URL=https://www.buymeacoffee.com/mlorente
PUBLIC_CALENDLY_URL=https://calendly.com/mlorentedev/videollamada
PUBLIC_TWITTER_URL=https://x.com/mlorentedev
PUBLIC_YOUTUBE_URL=https://www.youtube.com/@mlorentedev
PUBLIC_GITHUB_URL=https://github.com/mlorentedev

# Feature flags
PUBLIC_ENABLE_BLOG=false
PUBLIC_ENABLE_HOMELABS=true
PUBLIC_ENABLE_CONTACT=false

# Analytics & Tracking
PUBLIC_GOOGLE_ANALYTICS_ID=G-PLL8SP2YFC
PUBLIC_GOOGLE_TAG_MANAGER_ID=GTM-XXXXXX

# Deployment & Infrastructure
BACKEND_URL=http://backend:8080
EOL
    echo -e "${GREEN}.env.development file created successfully.${NC}"
else
    echo -e "${YELLOW}.env.development file already exists.${NC}"
fi

# Copy .env.development to frontend if it doesn't exist
if [ ! -f "frontend/.env" ]; then
    echo -e "${YELLOW}Copying .env.development to frontend/.env...${NC}"
    cp .env.development frontend/.env
    echo -e "${GREEN}.env file created successfully in frontend directory.${NC}"
else
    echo -e "${YELLOW}.env file already exists in frontend directory.${NC}"
fi

# Copy .env.development to backend if it doesn't exist
if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}Copying .env.development to backend/.env...${NC}"
    cp .env.development backend/.env
    echo -e "${GREEN}.env file created successfully in backend directory.${NC}"
else
    echo -e "${YELLOW}.env file already exists in backend directory.${NC}"
fi

# Create .air.toml for backend hot-reload
if [ ! -f "backend/.air.toml" ]; then
    echo -e "${YELLOW}Creating configuration for backend hot-reload...${NC}"
    mkdir -p backend
    cat > backend/.air.toml <<EOL
root = "."
tmp_dir = "tmp"
[build]
  bin = "./tmp/main"
  cmd = "go build -o ./tmp/main ./cmd/server"
  delay = 1000
  exclude_dir = ["assets", "tmp", "vendor"]
  exclude_file = []
  exclude_regex = ["_test.go"]
  exclude_unchanged = false
  follow_symlink = false
  full_bin = ""
  include_dir = []
  include_ext = ["go", "tpl", "tmpl", "html"]
  kill_delay = "0s"
  log = "build-errors.log"
  send_interrupt = false
  stop_on_error = true
[color]
  app = ""
  build = "yellow"
  main = "magenta"
  runner = "green"
  watcher = "cyan"
[log]
  time = false
[misc]
  clean_on_exit = false
EOL
    echo -e "${GREEN}.air.toml configuration created successfully.${NC}"
fi

# Start services in development mode
echo -e "${YELLOW}Do you want to start the services in development mode now? (y/n)${NC}"
read start_services

if [[ "$start_services" == "y" || "$start_services" == "Y" ]]; then
    echo -e "${GREEN}Starting services in development mode...${NC}"
    docker compose -f docker-compose.dev.yml up -d
    echo -e "${GREEN}Services started successfully.${NC}"
    echo -e "${YELLOW}Access the application at: http://localhost:3000${NC}"
else
    echo -e "${YELLOW}You can start the services later with: docker-compose -f docker-compose.dev.yml up -d${NC}"
fi

echo -e "${GREEN}Development environment setup complete.${NC}"