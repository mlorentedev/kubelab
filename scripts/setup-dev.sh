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

# Create .env.dev file if it doesn't exist
if [ ! -f ".env.dev" ]; then
    echo -e "${YELLOW}Creating .env.dev file...${NC}"
    cat > .env.dev <<EOL
# Environment Variables - Development
ENV=development

# Application
SITE_TITLE=mlorente.dev
SITE_DESCRIPTION=Manuel Lorente's personal blog
SITE_DOMAIN=localhost
SITE_URL=http://localhost:3000
SITE_MAIL=mlorentedev@gmail.com
SITE_AUTHOR=Manuel Lorente
SITE_KEYWORDS=devops, cloud, kubernetes, aws, azure, python, go

# Social media
TWITTER_URL=https://twitter.com/mlorentedev
YOUTUBE_URL=https://youtube.com/@mlorentedev
GITHUB_URL=https://github.com/mlorentedev
CALENDLY_URL=
BUY_ME_A_COFFEE_URL=

# Integrations
GOOGLE_ANALYTICS_ID=

# Feature flags
ENABLE_HOMELABS=true
ENABLE_BLOG=true
ENABLE_CONTACT=true

# API Backend
BACKEND_URL=http://backend:8080

# Beehiiv
BEEHIIV_API_KEY=dev_key
BEEHIIV_PUB_ID=dev_pub

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_SECURE=false
EMAIL_USER=
EMAIL_PASS=
EOL
    echo -e "${GREEN}.env.dev file created successfully.${NC}"
else
    echo -e "${YELLOW}.env.dev file already exists.${NC}"
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
    docker-compose -f docker-compose.dev.yml up -d
    echo -e "${GREEN}Services started successfully.${NC}"
    echo -e "${YELLOW}Access the application at: http://localhost:3000${NC}"
else
    echo -e "${YELLOW}You can start the services later with: docker-compose -f docker-compose.dev.yml up -d${NC}"
fi

echo -e "${GREEN}Development environment setup complete.${NC}"