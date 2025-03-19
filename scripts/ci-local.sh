#!/bin/bash
set -e

# Colors for better output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
FRONTEND_ONLY=false
BACKEND_ONLY=false
SKIP_DOCKER=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --frontend-only)
      FRONTEND_ONLY=true
      shift
      ;;
    --backend-only)
      BACKEND_ONLY=true
      shift
      ;;
    --skip-docker)
      SKIP_DOCKER=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--frontend-only] [--backend-only] [--skip-docker]"
      exit 1
      ;;
  esac
done

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

# Function to determine version (similar to GitHub Actions)
determine_version() {
  # Get current branch name
  local BRANCH=$(git rev-parse --abbrev-ref HEAD)
  local SHA_SHORT=$(git rev-parse --short HEAD)
  
  if [[ "$BRANCH" == "master" ]]; then
    echo "latest"
  elif [[ "$BRANCH" == "develop" ]]; then
    echo "develop"
  elif [[ "$BRANCH" =~ ^feature/.+ ]]; then
    local FEATURE_NAME=$(echo "$BRANCH" | sed 's|feature/||')
    echo "feature-${FEATURE_NAME}"
  elif [[ "$BRANCH" =~ ^hotfix/.+ ]]; then
    local HOTFIX_NAME=$(echo "$BRANCH" | sed 's|hotfix/||')
    echo "hotfix-${HOTFIX_NAME}"
  else
    echo "$SHA_SHORT"
  fi
}

# Determine version
VERSION=$(determine_version)
echo -e "${YELLOW}Building version: ${VERSION} (branch: $(git rev-parse --abbrev-ref HEAD))${NC}"

# Configure ownership of the project directory
echo -e "${YELLOW}Configuring ownership of the project directory...${NC}"
sudo chown -R $USER:$USER $(pwd)/frontend/ 2>/dev/null || echo "Skipping frontend ownership change"
sudo chown -R $USER:$USER $(pwd)/backend/ 2>/dev/null || echo "Skipping backend ownership change"

# Create artifacts directory
ARTIFACTS_DIR="$(pwd)/artifacts"
mkdir -p "${ARTIFACTS_DIR}/frontend"
mkdir -p "${ARTIFACTS_DIR}/backend/bin"

# ===================================
# FRONTEND CI
# ===================================
if [[ "$BACKEND_ONLY" == "false" ]]; then
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
  # Set environment variables similar to GitHub Actions
  ENV=$(git rev-parse --abbrev-ref HEAD | grep -q "master" && echo "production" || echo "staging")
  VERSION=$VERSION npm run build
  check_result "Frontend build"

  # Copy build artifacts
  echo -e "${YELLOW}Copying build artifacts...${NC}"
  cp -r dist/* "${ARTIFACTS_DIR}/frontend/"
  check_result "Frontend artifacts copying"

  echo -e "${GREEN}Frontend CI completed successfully${NC}"
  cd ..
fi

# ===================================
# BACKEND CI
# ===================================
if [[ "$FRONTEND_ONLY" == "false" ]]; then
  echo -e "\n${YELLOW}=== Testing Backend CI ===${NC}"
  cd backend

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

  # Try to run staticcheck if installed
  if command -v staticcheck &> /dev/null; then
    echo -e "${YELLOW}Running staticcheck...${NC}"
    staticcheck ./...
    check_result "Backend staticcheck"
  else
    echo -e "${YELLOW}Skipping staticcheck (not installed)${NC}"
  fi

  echo -e "${YELLOW}Building binaries...${NC}"
  mkdir -p bin
  
  # Set environment variables similar to GitHub Actions
  ENV=$(git rev-parse --abbrev-ref HEAD | grep -q "master" && echo "production" || echo "staging")
  
  # Build for multiple architectures like in GitHub Actions
  GOOS=linux GOARCH=amd64 go build -o ./bin/server-linux-amd64 ./cmd/server
  check_result "Backend amd64 build"
  
  GOOS=linux GOARCH=arm64 go build -o ./bin/server-linux-arm64 ./cmd/server 2>/dev/null || echo "Skipping arm64 build"

  # Copy build artifacts
  echo -e "${YELLOW}Copying build artifacts...${NC}"
  cp -r bin/* "${ARTIFACTS_DIR}/backend/bin/"
  check_result "Backend artifacts copying"

  echo -e "${GREEN}Backend CI completed successfully${NC}"
  cd ..
fi

# ===================================
# DOCKER IMAGES
# ===================================
if [[ "$SKIP_DOCKER" == "false" ]]; then
  echo -e "\n${YELLOW}=== Building Docker Images ===${NC}"

  # Login to DockerHub if credentials exist
  if [ -n "$DOCKERHUB_USERNAME" ] && [ -n "$DOCKERHUB_TOKEN" ]; then
    echo -e "${YELLOW}Logging into DockerHub...${NC}"
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
    check_result "DockerHub login"
  else
    echo -e "${YELLOW}DockerHub credentials not found. Images will be built locally only.${NC}"
  fi

  # Export the version as an environment variable for Docker builds
  export VERSION

  echo -e "${YELLOW}Building frontend image...${NC}"
  docker build -t mlorentedev/mlorente-frontend:local \
               -t mlorentedev/mlorente-frontend:$VERSION \
               -f docker/frontend/Dockerfile .
  check_result "Frontend Docker image build"

  echo -e "${YELLOW}Building backend image...${NC}"
  docker build -t mlorentedev/mlorente-backend:local \
               -t mlorentedev/mlorente-backend:$VERSION \
               -f docker/backend/Dockerfile .
  check_result "Backend Docker image build"
fi

echo -e "${BLUE}===============================================${NC}"
echo -e "${GREEN}CI LOCAL TESTING COMPLETED SUCCESSFULLY!${NC}"
echo -e "${BLUE}===============================================${NC}"
echo -e "${YELLOW}Version: ${VERSION}${NC}"
echo -e "${YELLOW}Artifacts location: ${ARTIFACTS_DIR}${NC}"
echo -e "${YELLOW}You can now run the CD testing script:${NC}"
echo -e "${BLUE}./cd-local.sh --environment staging --version ${VERSION}${NC}"