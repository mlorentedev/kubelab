#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration variables
VERSION=${1:-local}
PROJECT_ROOT=$(pwd)
TEST_DEPLOY_DIR=${PROJECT_ROOT}/deploy-test

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}      STARTING LOCAL CD TESTING PROCESS        ${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}Deploying version: ${VERSION}${NC}"

# Create deployment directory if it doesn't exist
mkdir -p $TEST_DEPLOY_DIR
cd $TEST_DEPLOY_DIR

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

# Force stop any existing test containers
echo -e "${YELLOW}Stopping any existing test containers...${NC}"
docker ps -a | grep "mlorente" | awk '{print $1}' | xargs docker rm -f 2>/dev/null || true

# Create a completely new docker-compose.yml for testing
echo -e "${YELLOW}Creating test docker-compose.yml...${NC}"
cat > docker-compose.yml <<EOL
services:
  frontend:
    container_name: mlorente-test-frontend
    image: mlorentedev/mlorente-frontend:local
    ports:
      - "4321:4321"
    env_file:
      - .env
    networks:
      - app-network
    depends_on:
      - backend

  backend:
    container_name: mlorente-test-backend
    image: mlorentedev/mlorente-backend:local
    ports:
      - "8080:8080"
    env_file:
      - .env
    networks:
      - app-network

  nginx:
    container_name: mlorente-test-nginx
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./docker/nginx/conf.d:/etc/nginx/conf.d
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    depends_on:
      - frontend
      - backend
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
EOL

# Set environment variables
echo -e "${YELLOW}Configuring environment...${NC}"
export TAG=$VERSION
export DOCKERHUB_USERNAME=mlorentedev

# Check if .env file exists, copy from example if not
if [ ! -f ".env" ]; then
  if [ -f "$PROJECT_ROOT/.env.example" ]; then
    echo -e "${YELLOW}Copying .env.example to .env for deployment...${NC}"
    cp "$PROJECT_ROOT/.env.example" .env
    
    # Update environment-specific values - CAMBIO CRÍTICO: usar 'development' en lugar de 'testing'
    sed -i "s/ENV=.*/ENV=development/" .env
    sed -i "s/VERSION=.*/VERSION=$VERSION/" .env
    sed -i "s/SITE_DOMAIN=.*/SITE_DOMAIN=localhost/" .env
    sed -i "s|SITE_URL=.*|SITE_URL=http://localhost:4321|" .env
    
    # Add specific backend URL for the test environment
    echo "PUBLIC_BACKEND_URL=http://localhost:8080" >> .env
    
    echo -e "${GREEN}✓ Deployment .env created and configured${NC}"
  else
    echo -e "${YELLOW}No .env.example found. Creating basic .env file for deployment...${NC}"
    cat > .env <<EOL
# Environment Variables
ENV=development
VERSION=$VERSION
PORT=8080
SITE_DOMAIN=localhost
SITE_URL=http://localhost:4321
DOCKERHUB_USERNAME=mlorentedev
PUBLIC_BACKEND_URL=http://localhost:8080
EOL
    echo -e "${YELLOW}⚠️ Created minimal .env file. Some features may not work properly.${NC}"
  fi
fi

# Create Nginx configuration directory if needed
if [ ! -d "docker/nginx/conf.d" ]; then
  mkdir -p docker/nginx/conf.d
fi

# Create Nginx configuration file
if [ ! -f "docker/nginx/conf.d/default.conf" ]; then
  echo -e "${YELLOW}Creating Nginx configuration...${NC}"
  cat > docker/nginx/conf.d/default.conf <<EOL
server {
    listen 80;
    server_name localhost;

    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Frontend
    location / {
        proxy_pass http://mlorente-test-frontend:4321;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Backend API
    location /api {
        proxy_pass http://mlorente-test-backend:8080;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Cache static assets
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|webp)$ {
        proxy_pass http://mlorente-test-frontend:4321;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        expires 7d;
        add_header Cache-Control "public";
    }

    # Let's Encrypt verification
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Error pages
    error_page 404 /404.html;
    error_page 500 502 503 504 /50x.html;
    
    # Healthcheck endpoint
    location /health {
        proxy_pass http://mlorente-test-backend:8080;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        access_log off;
    }
}
EOL
  echo -e "${GREEN}✓ Nginx configuration created${NC}"
else
  echo -e "${YELLOW}Nginx configuration already exists. Skipping creation.${NC}"
fi


# Check if images exist locally - if not, build them
echo -e "${YELLOW}Checking for local Docker images...${NC}"
if ! docker image inspect mlorentedev/mlorente-frontend:local &>/dev/null; then
  echo -e "${YELLOW}Building frontend image locally...${NC}"
  docker build -t mlorentedev/mlorente-frontend:local -f $PROJECT_ROOT/docker/frontend/Dockerfile $PROJECT_ROOT
fi

if ! docker image inspect mlorentedev/mlorente-backend:local &>/dev/null; then
  echo -e "${YELLOW}Building backend image locally...${NC}"
  docker build -t mlorentedev/mlorente-backend:local -f $PROJECT_ROOT/docker/backend/Dockerfile $PROJECT_ROOT
fi

# Deploy services
echo -e "${YELLOW}Deploying test services...${NC}"
docker compose up -d

# Verify services
echo -e "${YELLOW}Verifying services...${NC}"
docker compose ps

# Wait for services to be ready
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 10

# Execute health checks
echo -e "${YELLOW}Running health checks...${NC}"
FRONTEND_UP=false
BACKEND_UP=false

# Try up to 5 times with 5 second intervals
for i in {1..5}; do
    echo -e "${BLUE}Health check attempt $i/5${NC}"
    
    # Check frontend direct access
    FRONTEND_DIRECT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4321 || echo "000")
    if [ "$FRONTEND_DIRECT_STATUS" == "200" ]; then
        FRONTEND_UP=true
        echo -e "${GREEN}✓ Frontend direct access check passed ($FRONTEND_DIRECT_STATUS)${NC}"
    else
        echo -e "${RED}✗ Frontend direct access check failed ($FRONTEND_DIRECT_STATUS)${NC}"
    fi
    
    # Check backend health endpoint directly
    BACKEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health || echo "000")
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

# Final status
if $FRONTEND_UP && $BACKEND_UP; then
    echo -e "${GREEN}All health checks passed successfully!${NC}"
else
    echo -e "${RED}Some health checks failed. Service might not be fully operational.${NC}"
    echo -e "${YELLOW}Displaying logs:${NC}"
    docker compose logs
fi

echo -e "${BLUE}===============================================${NC}"
echo -e "${GREEN}CD LOCAL TESTING COMPLETED!${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}Application is running at:${NC}"
echo -e "${BLUE}- Frontend: http://localhost:${LOCAL_FRONTEND_PORT}${NC}"
echo -e "${BLUE}- Backend: http://localhost:${LOCAL_BACKEND_PORT}/api/health${NC}"
echo -e "${BLUE}- Nginx: http://localhost:${LOCAL_NGINX_PORT}${NC}"
echo -e ""
echo -e "${YELLOW}You can view test logs with: ${NC}${BLUE}cd ${TEST_DEPLOY_DIR} && docker compose logs -f${NC}"
echo -e "${YELLOW}To clean up test environment: ${NC}${BLUE}cd ${TEST_DEPLOY_DIR} && docker compose down -v${NC}"