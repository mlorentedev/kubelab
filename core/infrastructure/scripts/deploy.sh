#!/bin/bash
# deploy.sh

# Get the directory of the script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Load utility functions
if [ ! -f "$PROJECT_DIR/scripts/utils.sh" ]; then
  echo "Error: utils.sh not found. Please ensure it exists."
  exit 1
fi
source "$PROJECT_DIR/scripts/utils.sh"

# Check if version of Docker Compose is compatible
MIN_VERSION="1.26"
DOCKER_VERSION=$(docker version --format '{{.Client.APIVersion}}')
if [ "$(printf '%s\n' "$MIN_VERSION" "$DOCKER_VERSION" | sort -V | head -n1)" = "$MIN_VERSION" ] && [ "$DOCKER_VERSION" != "$MIN_VERSION" ]; then
  log_info "Docker Compose v1.26 or lower detected. Updating docker-compose to use version 2."
  DOCKER_COMPOSE_COMMAND="docker-compose"
else
  log_info "Docker Compose v1.27 or higher detected. Using docker compose command."
  DOCKER_COMPOSE_COMMAND="docker compose"
fi

# Function to deploy a specific environment
deploy_environment() {
  local env=$1
  
  # Skip non-environment deployments
  if [ "$env" == "all" ] || [ "$env" == "common" ]; then
    return 0
  fi
  
  # Load environment variables
  if [ ! -f ".env.$env" ]; then
    log_error "Environment file .env.$env not found."
    return 1
  fi

  if [ -f ".env" ]; then
    log_info "Removing existing .env file to avoid conflicts."
    rm .env
  fi  
  
  # Load the environment variables
  log_info "Loading environment from .env.$env"
  cp ".env.$env" .env
  source .env
  
  # Deploy the environment
  log_info "Deploying $env environment..."
  $DOCKER_COMPOSE_COMMAND -f docker-compose.$env.yml up -d
  
  log_success "$env environment deployed successfully."
}

# Function to deploy common services (Traefik)
deploy_common() {
  local env=${1:-staging}
  
  # Select appropriate environment file
  if [ "$env" == "staging" ]; then
    log_info "Loading STAGING environment for Traefik configuration"
    cp ".env.staging" .env
  elif [ "$env" == "production" ]; then
    log_info "Loading PRODUCTION environment for Traefik configuration"
    cp ".env.production" .env
  else
    log_error "Invalid environment for Traefik configuration."
    return 1
  fi
    
  # Generate Traefik configuration
  ./scripts/generate-traefik-config.sh
  
  # Recreate acme.json file and permissions
  if [ -f "traefik/acme.json" ]; then
    log_info "Removing existing acme.json file"
    rm traefik/acme.json
  fi
  log_info "Creating acme.json file"
  touch traefik/acme.json
  chmod 600 traefik/acme.json
  
  # Deploy Traefik
  log_info "Deploying Traefik..."
  $DOCKER_COMPOSE_COMMAND -f docker-compose.traefik.yml up -d
  
  log_success "Traefik deployed successfully."
}

# Main script execution
ACTION=${1:-deploy}
ENVIRONMENT=${2:-all}

# Validate action
if [ "$ACTION" != "deploy" ] && [ "$ACTION" != "stop" ]; then
  log_error "Invalid action: $ACTION. Use 'deploy' or 'stop'."
  exit 1
fi

# Validate environment
if [ "$ENVIRONMENT" != "staging" ] && [ "$ENVIRONMENT" != "production" ] && [ "$ENVIRONMENT" != "common" ] && [ "$ENVIRONMENT" != "all" ]; then
  log_error "Invalid environment: $ENVIRONMENT. Use 'staging', 'production', 'common', or 'all'."
  exit 1
fi

# Perform the requested action
if [ "$ACTION" == "deploy" ]; then
  # Deploy the requested environment(s)
  if [ "$ENVIRONMENT" == "all" ]; then
    deploy_common "production"
    deploy_environment "staging"
    deploy_environment "production"
  elif [ "$ENVIRONMENT" == "common" ]; then
    deploy_common
  elif [ "$ENVIRONMENT" == "staging" ]; then
    deploy_common "staging"
    deploy_environment "staging"
  elif [ "$ENVIRONMENT" == "production" ]; then
    deploy_common "production"
    deploy_environment "production"
  fi
elif [ "$ACTION" == "stop" ]; then
  # Stop the requested environment(s)
  if [ "$ENVIRONMENT" == "all" ]; then
    log_info "Stopping all environments..."
    $DOCKER_COMPOSE_COMMAND -f docker-compose.production.yml down --remove-orphans
    $DOCKER_COMPOSE_COMMAND -f docker-compose.staging.yml down --remove-orphans
    $DOCKER_COMPOSE_COMMAND -f docker-compose.traefik.yml down --remove-orphans
  elif [ "$ENVIRONMENT" == "common" ]; then
    log_info "Stopping Traefik..."
    $DOCKER_COMPOSE_COMMAND -f docker-compose.traefik.yml down --remove-orphans
  else
    log_info "Stopping $ENVIRONMENT environment..."
    $DOCKER_COMPOSE_COMMAND -f docker-compose.$ENVIRONMENT.yml down --remove-orphans
  fi
  
  log_success "Stop operation completed successfully."
fi