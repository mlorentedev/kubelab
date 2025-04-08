# Makefile for mlorente.dev management
SHELL := /bin/zsh
.SHELLFLAGS := -c -l

# Variables - Main ssh configuration is in ~/.ssh/config
SSH_KEY = ~/.ssh/id_ed25519
DEPLOYMENT_PATH = ./deployment
ANSIBLE_PATH = $(DEPLOYMENT_PATH)/ansible
PLAYBOOK_PATH = $(ANSIBLE_PATH)/playbooks
INVENTORY_PATH = $(ANSIBLE_PATH)/inventory
DOCKER_COMPOSE_PATH = $(DEPLOYMENT_PATH)/docker
DOCKER_COMPOSE_LOCAL = $(DOCKER_COMPOSE_PATH )/docker-compose.local.yml

# Include utils.sh
UTILS_PATH = ./shared/scripts/utils.sh

# Define log functions for use in Makefile
define log_info
	@bash -c 'source $(UTILS_PATH) && log_info "$1"'
endef

define log_success
	@bash -c 'source $(UTILS_PATH) && log_success "$1"'
endef

define log_warning
	@bash -c 'source $(UTILS_PATH) && log_warning "$1"'
endef

define log_error
	@bash -c 'source $(UTILS_PATH) && log_error "$1"'
endef

define check_command
	@bash -c 'source $(UTILS_PATH) && check_command "$1" "$2"'
endef

define exit_error
	@bash -c 'source $(UTILS_PATH) && exit_error "$1" "$2"'
endef

# Determine default environment
ENV ?= staging
INVENTORY = $(INVENTORY_PATH)/hosts.yml

.PHONY: help setup dev deploy-local deploy update rollback logs status clean generate-config generate-auth install-deps install-ansible check

# Help
help:
	$(call log_info,Development commands:)
	@echo "  make install-deps         # Install development dependencies"
	@echo "  make install-ansible      # Install Ansible and dependencies"
	@echo "  make dev                  # Start local development environment"
	@echo "  make clean                # Clean local resources"
	@echo "  make generate-config      # Generate Traefik configuration"
	@echo "  make generate-auth        # Generate authentication credentials"
	@echo "  make copy-certificates    # Copy certificates to the local directory"
	@echo ""
	$(call log_info,Deployment commands:)
	@echo "  make check                # Verify prerequisites"
	@echo "  make setup ENV=<env>      # Initial environment setup (staging|production)"
	@echo "  make deploy ENV=<env>     # Deploy application (staging|production)"
	@echo "  make update ENV=<env>     # Update application without restarting services"
	@echo "  make rollback ENV=<env>   # Rollback to previous deployment"
	@echo "  make logs ENV=<env>       # View application logs"
	@echo "  make status ENV=<env>     # View service status"

# Check requirements
check:
	$(call log_info,Verifying prerequisites...)
	$(call check_command,ansible,ansible)
	$(call check_command,docker,docker)
	$(call check_command,awk,awk)
	$(call check_command,docker-compose,docker-compose)
	$(call log_success,All requirements are met.)

# Install development dependencies
install-deps:
	$(call log_info,Installing development dependencies...)
	@if [ -f "./services/frontend/package.json" ]; then \
		which npm > /dev/null || ($(call log_error,npm is not installed.) && exit 1); \
		cd ./services/frontend && npm install; \
	fi
	@if [ -f "./services/frontend/Gemfile" ]; then \
		which ruby > /dev/null || ($(call log_error,Ruby is not installed.) && exit 1); \
		$(RUBY_HOME)/bin/gem install bundler; \
		cd ./services/frontend && $(RUBY_HOME)/bin/gem exec bundler install || \
			($(call log_error,Error installing Ruby dependencies.) && exit 1); \
	fi
	$(call log_success,Dependencies installed.)

# Install Ansible
install-ansible:
	$(call log_info,Installing Ansible and dependencies...)
	@if [ -x "$(command -v apt-get)" ]; then \
		sudo apt-get update && sudo apt-get install -y python3 python3-pip; \
	elif [ -x "$(command -v brew)" ]; then \
		brew install python3; \
	fi
	$(PYTHON_HOME)/bin/python3 -m pip install ansible docker paramiko
	ansible-galaxy collection install community.docker
	$(call log_success,Ansible successfully installed.)

# Start development environment
dev: check generate-config
	$(call log_info,Starting local development environment...)
	@docker network create traefik_network 2>/dev/null || true
	@if [ ! -f ".env.local" ]; then \
		$(call log_error,.env.local file not found. Create one based on .env.example); \
		exit 1; \
	fi
	@cp .env.local deploymeny/docker/.env
	@chmod +x ./shared/scripts/*.sh
	@./shared/scripts/generate-traefik-config.sh
	@docker compose -f $(DOCKER_COMPOSE_LOCAL) up -d --build
	$(call log_success,Development environment started at http://0.0.0.0:4000)

# Initial setup
setup: check
	$(call log_info,Setting up $(ENV) environment...)
	@if [ ! -f "$(INVENTORY)" ]; then \
		$(call log_error,Inventory file $(INVENTORY) not found); \
		exit 1; \
	fi
	ansible-playbook $(PLAYBOOK_PATH)/setup.yml -i $(INVENTORY) --limit $(ENV) -e "env=$(ENV)" --private-key $(SSH_KEY) --ask-become-pass -v

# Deploy application
deploy: check generate-config
	$(call log_info,Deploying to $(ENV)...)
	ansible-playbook $(PLAYBOOK_PATH)/deploy.yml -i $(INVENTORY) --limit $(ENV) -e "env=$(ENV)" --private-key $(SSH_KEY) --ask-become-pass -v

# Update application
update: check
	$(call log_info,Updating application in $(ENV)...)
	ansible-playbook $(PLAYBOOK_PATH)/update.yml -i $(INVENTORY) --limit $(ENV) -e "env=$(ENV)"

# Rollback to previous deployment
rollback: check
	$(call log_info,Rolling back in $(ENV)...)
	ansible-playbook $(PLAYBOOK_PATH)/rollback.yml -i $(INVENTORY) --limit $(ENV) -e "env=$(ENV)"

# View logs
logs: check
	$(call log_info,Getting logs from $(ENV)...)
	ansible $(ENV) -i $(INVENTORY) -m shell -a "docker logs jekyll-$(ENV)" 

# View service status
status: check
	$(call log_info,Checking status in $(ENV)...)
	ansible $(ENV) -i $(INVENTORY) -m shell -a "docker ps"

# Clean local resources
clean:
	$(call log_info,Cleaning local resources...)
	docker compose -f $(DOCKER_COMPOSE_LOCAL) down --remove-orphans
	docker volume prune -f
	$(call log_success,Local resources cleaned.)

# Generate environment-specific configuration files
generate-config:
	$(call log_info,Generating Traefik and Ansible configuration files...)
	@chmod +x ./shared/scripts/generate-traefik-config.sh
	@chmod +x ./shared/scripts/generate-ansible-config.sh
	@cp .env deployment/docker/.env
	@cp .env deployment/ansible/.env
	@./shared/scripts/generate-traefik-config.sh
	@./shared/scripts/generate-ansible-config.sh
	$(call log_success,Configuration files generated successfully.)

# Generate authentication credentials for Traefik
generate-auth:
	$(call log_info,Generating authentication credentials for Traefik...)
	@chmod +x ./shared/scripts/generate-traefik-credentials.sh
	@./shared/scripts/generate-traefik-credentials.sh
	$(call log_success,Credentials successfully generated.)

# Copy certificates to the appropriate directory
copy-certificates:
	$(call log_info,Copying certificates to the appropriate directory...)
	@scp mlorente-deployer:/opt/traefik/acme.json /tmp/acme.json
	$(call log_success,Certificates copied to /tmp/acme.json successfully.)
	@chmod 600 /tmp/acme.json
	@cat /tmp/acme.json | jq -r '.myresolver.Certificates[0].certificate' | base64 -d > /tmp/staging-cert.crt
	@cat /tmp/acme.json | jq -r '.myresolver.Certificates[0].key' | base64 -d > /tmp/staging-key.key
	$(call log_success,Certificates extracted successfully.)
	@sudo cp /tmp/staging-cert.crt /tmp/staging-key.key /usr/local/share/ca-certificates/
	$(call log_info,Updating CA certificates...)
	@sudo update-ca-certificates
	$(call log_success,Certificates copied successfully.)