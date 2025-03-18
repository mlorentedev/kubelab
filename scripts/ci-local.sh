#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}      STARTING LOCAL CI TESTING PROCESS        ${NC}"
echo -e "${BLUE}===============================================${NC}"

# Function to check result and print status
check_result() {
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ $1 passed${NC}"
  else
    echo -e "${RED}✗ $1 failed${NC}"
    exit 1
  fi
}

# Configure ownership of the project directory
echo -e "${YELLOW}Configuring ownership of the project directory...${NC}"
sudo chown -R $USER:$USER $(pwd)/frontend/
sudo chown -R $USER:$USER $(pwd)/backend/

# ===================================
# FRONTEND CI
# ===================================
echo -e "\n${YELLOW}=== Testing Frontend CI ===${NC}"
cd frontend

# Check if .env file exists, copy from example if not
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo -e "${YELLOW}Copying .env.example to .env for frontend...${NC}"
    cp .env.example .env
    check_result "Frontend .env creation"
  else
    echo -e "${RED}No .env.example file found for frontend. Please create an .env file manually.${NC}"
    exit 1
  fi
fi

echo -e "${YELLOW}Installing dependencies...${NC}"
npm ci
check_result "Frontend dependencies installation"

echo -e "${YELLOW}Running linting...${NC}"
npm run lint
check_result "Frontend linting"

echo -e "${YELLOW}Type checking...${NC}"
npm run astro check
check_result "Frontend type checking"

echo -e "${YELLOW}Building frontend...${NC}"
npm run build
check_result "Frontend build"

echo -e "${GREEN}Frontend CI completed successfully${NC}"

# ===================================
# BACKEND CI
# ===================================
echo -e "\n${YELLOW}=== Testing Backend CI ===${NC}"
cd ../backend

# Check if .env file exists, copy from example if not
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo -e "${YELLOW}Copying .env.example to .env for backend...${NC}"
    cp .env.example .env
    check_result "Backend .env creation"
  else
    echo -e "${RED}No .env.example file found for backend. Please create an .env file manually.${NC}"
    exit 1
  fi
fi

echo -e "${YELLOW}Verifying dependencies...${NC}"
go mod verify
check_result "Backend dependency verification"

echo -e "${YELLOW}Running static analysis...${NC}"
go vet ./...
check_result "Backend static analysis"

echo -e "${YELLOW}Running tests...${NC}"
go test -race -coverprofile=coverage.txt -covermode=atomic ./...
check_result "Backend tests"

echo -e "${YELLOW}Building binaries...${NC}"
mkdir -p bin
GOOS=linux GOARCH=amd64 go build -o ./bin/server-linux-amd64 ./cmd/server
check_result "Backend binary build"

echo -e "${GREEN}Backend CI completed successfully${NC}"

# ===================================
# DOCKER IMAGES
# ===================================
echo -e "\n${YELLOW}=== Building Docker Images ===${NC}"
cd ..

echo -e "${YELLOW}Building frontend image...${NC}"
docker build -t mlorentedev/mlorente-frontend:local -f docker/frontend/Dockerfile .
check_result "Frontend Docker image build"

echo -e "${YELLOW}Building backend image...${NC}"
docker build -t mlorentedev/mlorente-backend:local -f docker/backend/Dockerfile .
check_result "Backend Docker image build"

echo -e "${BLUE}===============================================${NC}"
echo -e "${GREEN}CI LOCAL TESTING COMPLETED SUCCESSFULLY!${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}You can now run the CD testing script:${NC}"
echo -e "${BLUE}./scripts/cd-local.sh local${NC}"