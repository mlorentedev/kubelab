#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="staging"
VERSION="local"
SKIP_BUILD=false
CREATE_RELEASE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --environment|-e)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --version|-v)
      VERSION="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=true
      shift
      ;;
    --create-release)
      CREATE_RELEASE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--environment|-e staging|production] [--version|-v VERSION] [--skip-build] [--create-release]"
      exit 1
      ;;
  esac
done

# Validate environment
if [[ "$ENVIRONMENT" != "staging" && "$ENVIRONMENT" != "production" ]]; then
  echo -e "${RED}Invalid environment. Must be 'staging' or 'production'.${NC}"
  exit 1
fi

# Configuration variables
PROJECT_ROOT=$(pwd)
TEST_DEPLOY_DIR=${PROJECT_ROOT}/deploy-${ENVIRONMENT}

# Define port variables based on environment
if [[ "$ENVIRONMENT" == "production" ]]; then
  LOCAL_FRONTEND_PORT=5001
  LOCAL_BACKEND_PORT=5002
  LOCAL_NGINX_PORT=5000
  DOMAIN="localhost:$LOCAL_NGINX_PORT"
else
  LOCAL_FRONTEND_PORT=4001
  LOCAL_BACKEND_PORT=4002
  LOCAL_NGINX_PORT=4000
  DOMAIN="localhost:$LOCAL_NGINX_PORT"
fi

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}      STARTING LOCAL CD TESTING PROCESS        ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo -e "${YELLOW}Deploying version: ${VERSION}${NC}"

# Prepare stage - similar to GitHub Actions prepare job
echo -e "${YELLOW}=== Prepare Stage ===${NC}"

# If version is not specified, determine it based on current branch
if [[ "$VERSION" == "local" ]]; then
  if [[ "$ENVIRONMENT" == "production" ]]; then
    VERSION="latest"
  else
    VERSION="develop"
  fi
  echo -e "${YELLOW}Using determined version: ${VERSION}${NC}"
fi

# Create deployment directory if it doesn't exist
mkdir -p $TEST_DEPLOY_DIR
cd $TEST_DEPLOY_DIR

# Configure ownership of the project directory
sudo chown -R $USER:$USER $TEST_DEPLOY_DIR 2>/dev/null || echo "Skipping ownership change"

# Check if the directory is clean
if [ "$(ls -A $TEST_DEPLOY_DIR)" ]; then
    echo -e "${YELLOW}Test deployment directory is not empty.${NC}"
    read -p "Do you want to clean it before proceeding? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cleaning test deployment directory...${NC}"
        docker-compose down -v 2>/dev/null || true
        rm -rf * .*
    fi
fi

# Force stop any existing test containers for this environment
echo -e "${YELLOW}Stopping any existing test containers...${NC}"
docker ps -a | grep "mlorente-${ENVIRONMENT}" | awk '{print $1}' | xargs docker rm -f 2>/dev/null || true

# Create a docker-compose.yml for testing - adapted for environment
echo -e "${YELLOW}Creating test docker-compose.yml...${NC}"
cat > docker-compose.yml <<EOL
services:
  frontend:
    container_name: mlorente-${ENVIRONMENT}-frontend
    image: mlorentedev/mlorente-frontend:${VERSION}
    ports:
      - "${LOCAL_FRONTEND_PORT}:4321"
    environment:
      - HOST=0.0.0.0      
    env_file:
      - .env
    networks:
      - app-network
    depends_on:
      - backend

  backend:
    container_name: mlorente-${ENVIRONMENT}-backend
    image: mlorentedev/mlorente-backend:${VERSION}
    ports:
      - "${LOCAL_BACKEND_PORT}:8080"
    env_file:
      - .env
    networks:
      - app-network

  nginx:
    container_name: mlorente-${ENVIRONMENT}-nginx
    image: nginx:alpine
    ports:
      - "${LOCAL_NGINX_PORT}:80"
    volumes:
      - ./docker/nginx/conf.d:/etc/nginx/conf.d
    depends_on:
      - frontend
      - backend
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
EOL

# Deploy stage - similar to GitHub Actions deploy job
echo -e "${YELLOW}=== Deploy Stage ===${NC}"

# Set environment variables
echo -e "${YELLOW}Configuring environment...${NC}"
export TAG=$VERSION
export DOCKERHUB_USERNAME=mlorentedev

# Create a timestamp for backups
TIMESTAMP=$(date +%Y%m%d%H%M%S)
BACKUP_DIR="./backups/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"

# Backup existing configuration if any
if [ -f ".env" ]; then
  echo -e "${YELLOW}Backing up existing configuration...${NC}"
  cp ".env" "${BACKUP_DIR}/.env.backup"
fi

# Check if .env file exists, copy from example if not
if [ ! -f ".env" ]; then
  if [ -f "$PROJECT_ROOT/.env.example" ]; then
    echo -e "${YELLOW}Copying .env.example to .env for deployment...${NC}"
    cp "$PROJECT_ROOT/.env.example" .env
    
    # Update environment-specific values
    sed -i "s/ENV=.*/ENV=${ENVIRONMENT}/" .env
    sed -i "s/VERSION=.*/VERSION=${VERSION}/" .env
    sed -i "s/SITE_DOMAIN=.*/SITE_DOMAIN=${DOMAIN}/" .env
    sed -i "s|SITE_URL=.*|SITE_URL=http://${DOMAIN}|" .env
    
    # Add specific backend URL for the test environment
    echo "BACKEND_URL=http://backend:${LOCAL_BACKEND_PORT}" >> .env
    echo "HOST=0.0.0.0" >> .env

    echo -e "${GREEN}✓ Deployment .env created and configured${NC}"
  else
    echo -e "${YELLOW}No .env.example found. Creating basic .env file for deployment...${NC}"
    cat > .env <<EOL
# Environment Variables
ENV=${ENVIRONMENT}
VERSION=${VERSION}
HOST=0.0.0.0
PORT=8080
SITE_DOMAIN=${DOMAIN}
SITE_URL=http://${DOMAIN}
DOCKERHUB_USERNAME=mlorentedev
BACKEND_URL=http://backend:${LOCAL_BACKEND_PORT}
PUBLIC_SITE_TITLE=mlorente.dev
PUBLIC_SITE_DESCRIPTION=mlorentedev site (${ENVIRONMENT})
PUBLIC_SITE_DOMAIN=${DOMAIN}
PUBLIC_SITE_URL=http://${DOMAIN}
PUBLIC_SITE_MAIL=mlorentedev@gmail.com
PUBLIC_SITE_AUTHOR=Manuel Lorente
PUBLIC_ENABLE_HOMELABS=true
PUBLIC_ENABLE_BLOG=false
PUBLIC_ENABLE_CONTACT=false
EOL
    echo -e "${YELLOW}⚠️ Created minimal .env file. Some features may not work properly.${NC}"
  fi
fi

# Create Nginx configuration directory if needed
mkdir -p docker/nginx/conf.d

# Create Nginx configuration file
echo -e "${YELLOW}Creating Nginx configuration...${NC}"
cat > docker/nginx/conf.d/default.conf <<EOL
server {
    listen 80;
    server_name localhost;

    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Frontend
    location / {
        proxy_pass http://frontend:4321;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;    
    }

    # Backend API
    location /api {
        proxy_pass http://backend:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://backend:8080/health;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        access_log off;
    }

    # Cache static assets
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|webp)$ {
        proxy_pass http://frontend:4321;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_cache_bypass \$http_upgrade;
        expires 7d;
        add_header Cache-Control "public";
    }
}
EOL
echo -e "${GREEN}✓ Nginx configuration created${NC}"

# Build Docker images if needed
if [[ "$SKIP_BUILD" == "false" ]]; then
  echo -e "${YELLOW}Checking for Docker images...${NC}"
  
  if ! docker image inspect mlorentedev/mlorente-frontend:$VERSION &>/dev/null; then
    echo -e "${YELLOW}Building frontend image...${NC}"
    docker build -t mlorentedev/mlorente-frontend:$VERSION -f $PROJECT_ROOT/docker/frontend/Dockerfile $PROJECT_ROOT
  else
    echo -e "${GREEN}✓ Frontend image already exists: mlorentedev/mlorente-frontend:${VERSION}${NC}"
  fi

  if ! docker image inspect mlorentedev/mlorente-backend:$VERSION &>/dev/null; then
    echo -e "${YELLOW}Building backend image...${NC}"
    docker build -t mlorentedev/mlorente-backend:$VERSION -f $PROJECT_ROOT/docker/backend/Dockerfile $PROJECT_ROOT
  else
    echo -e "${GREEN}✓ Backend image already exists: mlorentedev/mlorente-backend:${VERSION}${NC}"
  fi
fi

# Deploy services - similar to GitHub Actions deploy steps
echo -e "${YELLOW}Deploying services...${NC}"
docker compose pull || echo -e "${YELLOW}Pull failed, using local images${NC}"
docker compose up -d

# Verify services
echo -e "${YELLOW}Verifying services...${NC}"
docker compose ps

# Wait for services to be ready
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 10

# Execute health checks - similar to GitHub Actions health checks
echo -e "${YELLOW}Running health checks...${NC}"
FRONTEND_UP=false
BACKEND_UP=false

# Try up to 5 times with 5 second intervals
for i in {1..5}; do
    echo -e "${BLUE}Health check attempt $i/5${NC}"
    
    # Check frontend via nginx
    FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${LOCAL_NGINX_PORT} || echo "000")
    if [ "$FRONTEND_STATUS" == "200" ]; then
        FRONTEND_UP=true
        echo -e "${GREEN}✓ Frontend check passed ($FRONTEND_STATUS)${NC}"
    else
        # Try direct access to frontend as a fallback
        FRONTEND_DIRECT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${LOCAL_FRONTEND_PORT} || echo "000")
        if [ "$FRONTEND_DIRECT_STATUS" == "200" ]; then
            FRONTEND_UP=true
            echo -e "${GREEN}✓ Frontend direct access check passed ($FRONTEND_DIRECT_STATUS)${NC}"
        else
            echo -e "${RED}✗ Frontend checks failed (Nginx: $FRONTEND_STATUS, Direct: $FRONTEND_DIRECT_STATUS)${NC}"
        fi
    fi
    
    # Check backend health endpoint
    BACKEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${LOCAL_BACKEND_PORT}/health || echo "000")
    if [ "$BACKEND_STATUS" == "200" ]; then
        BACKEND_UP=true
        echo -e "${GREEN}✓ Backend health check passed ($BACKEND_STATUS)${NC}"
    else
        echo -e "${RED}✗ Backend health check failed ($BACKEND_STATUS)${NC}"
    fi

    if $FRONTEND_UP && $BACKEND_UP; then
        echo -e "${GREEN}All services are up and healthy!${NC}"
        break
    fi

    echo -e "${YELLOW}Waiting for services to become healthy...${NC}"
    sleep 5
done

# Release stage - similar to GitHub Actions release job
if [[ "$ENVIRONMENT" == "production" && "$CREATE_RELEASE" == "true" ]]; then
    echo -e "${YELLOW}=== Release Stage ===${NC}"
    
    # Generate semver tag
    CURRENT_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    
    # Extract components
    IFS='.' read -r -a VERSION_PARTS <<< "${CURRENT_TAG//v/}"
    MAJOR=${VERSION_PARTS[0]}
    MINOR=${VERSION_PARTS[1]}
    PATCH=${VERSION_PARTS[2]}
    
    # Increment patch version
    PATCH=$((PATCH + 1))
    NEW_TAG="v$MAJOR.$MINOR.$PATCH"
    
    echo -e "${YELLOW}Creating release tag: ${NEW_TAG}${NC}"
    
    # Create a local tag
    git tag -a $NEW_TAG -m "Release $NEW_TAG (local test)" || echo -e "${YELLOW}Skipping tag creation (might already exist)${NC}"
    
    # Tag Docker images with release version
    echo -e "${YELLOW}Tagging Docker images with release version...${NC}"
    docker tag mlorentedev/mlorente-frontend:$VERSION mlorentedev/mlorente-frontend:$NEW_TAG
    docker tag mlorentedev/mlorente-backend:$VERSION mlorentedev/mlorente-backend:$NEW_TAG
    
    echo -e "${GREEN}✓ Release ${NEW_TAG} created locally${NC}"
    echo -e "${YELLOW}To push this release, you would run:${NC}"
    echo -e "${BLUE}git push origin ${NEW_TAG}${NC}"
    echo -e "${BLUE}docker push mlorentedev/mlorente-frontend:${NEW_TAG}${NC}"
    echo -e "${BLUE}docker push mlorentedev/mlorente-backend:${NEW_TAG}${NC}"
fi

# Final status
if $FRONTEND_UP && $BACKEND_UP; then
    echo -e "${GREEN}All health checks passed successfully!${NC}"
else
    echo -e "${RED}Some health checks failed. Service might not be fully operational.${NC}"
    echo -e "${YELLOW}Displaying logs:${NC}"
    docker compose logs
    exit 1
fi

echo -e "${BLUE}===============================================${NC}"
echo -e "${GREEN}CD LOCAL TESTING COMPLETED!${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo -e "${YELLOW}Version: ${VERSION}${NC}"
echo -e "${YELLOW}Application is running at:${NC}"
echo -e "${BLUE}- Frontend: http://localhost:${LOCAL_FRONTEND_PORT}${NC}"
echo -e "${BLUE}- Backend: http://localhost:${LOCAL_BACKEND_PORT}/health${NC}"
echo -e "${BLUE}- Nginx: http://localhost:${LOCAL_NGINX_PORT}${NC}"
echo -e ""
echo -e "${YELLOW}You can view logs with: ${NC}${BLUE}cd ${TEST_DEPLOY_DIR} && docker compose logs -f${NC}"
echo -e "${YELLOW}To clean up: ${NC}${BLUE}cd ${TEST_DEPLOY_DIR} && docker compose down -v${NC}"