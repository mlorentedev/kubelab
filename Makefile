# Makefile for mlorente.dev management
SHELL := /bin/zsh
.SHELLFLAGS := -c -l

ifneq (,$(wildcard .env))
  include .env
  export
endif

define log_info
	@bash -c 'source "$(SCRIPTS_PATH)/utils.sh"; log_info "$$1"' dummy "$(1)"
endef

define log_success
	@bash -c 'source "$(SCRIPTS_PATH)/utils.sh"; log_success "$$1"' dummy "$(1)"
endef

define log_warning
	@bash -c 'source "$(SCRIPTS_PATH)/utils.sh"; log_warning "$$1"' dummy "$(1)"
endef

define log_error
	@bash -c 'source "$(SCRIPTS_PATH)/utils.sh"; log_error "$$1"' dummy "$(1)"
endef

define check_command
	@bash -c 'source "$(SCRIPTS_PATH)/utils.sh"; check_command "$$1" "$$2"' dummy "$(1)" "$(2)"
endef

.PHONY: help check install-deps install-ansible create-network \
		up-traefik up-n8n up-monitoring up-blog up-web up-api up \
		setup deploy status down down-traefik down-n8n down-monitoring down-web down-blog down-api down \
		generate-config generate-traefik-credentials generate-traefik-config generate-ansible-config copy-certificates create-env-example setup-secrets list-secrets \
		validate-yaml lint-workflows

help:
	$(call log_info,Installation and setup commands:)
	@echo "  make check                			- Check prerequisites"
	@echo "  make install-node	   				- Install NPM dependencies for WEB"
	@echo "  make install-ruby         			- Install Ruby and Bundler dependencies for BLOG"
	@echo "  make install-ansible      			- Install Ansible and dependencies"
	@echo "  make create-network       			- Create Docker network if it does not exist"
	$(call log_info,Development commands:)
	@echo "  make dev-web             			- Start local development environment for WEB"
	@echo "  make dev-api             			- Start local development environment for API"
	@echo "  make dev-blog            			- Start local development environment for BLOG"
	@echo "  make dev-traefik         			- Start local development environment for Traefik"
	@echo "  make dev                 			- Start all local development environments"
	$(call log_info,Server deployment commands:)
	@echo "  make setup               			- Initial setup for the environment"
	@echo "  make deploy              			- Deploy application to the environment"
	@echo "  make status              			- View service status in the environment"
	$(call log_info,Utility commands:)
	@echo "  make clean               			- Clean local resources"
	@echo "  make generate-config     			- Generate all configuration files from templates"
	@echo "  make generate-traefik-credentials 		- Generate authentication credentials for Traefik"
	@echo "  make generate-traefik-config 			- Generate Traefik configuration files from templates"
	@echo "  make generate-ansible-config 			- Generate Ansible configuration files from templates"
	@echo "  make copy-certificates   			- Copy self-signed SSL certificates to the in the local machine"
	@echo "  make setup-secrets       			- Configure GitHub secrets from .env files"
	@echo "  make list-secrets        			- List configured GitHub secrets"
	@echo "  make create-env-example  			- Create .env.example from .env files"
	$(call log_info,Pipeline testing commands:)
	@echo "  make validate-yaml       			- Validate all YAML files"
	@echo "  make lint-workflows      			- Lint GitHub Actions workflows"

############################################################################################
# Installation and setup commands
############################################################################################

check:
	$(call log_info,Verifying prerequisites...)
	$(call check_command,ansible,ansible)
	$(call check_command,docker,docker)
	$(call check_command,npm,npm)
	$(call check_command,bundle,bundle)
	$(call check_command,ruby,ruby)
	$(call check_command,python3,python3)
	$(call check_command,pip3,pip3)
	$(call check_command,gh,gh)
	$(call check_command,jq,jq)
	$(call check_command,yamllint,yamllint)
	$(call check_command,actionlint,actionlint)
	$(call check_command,awk,awk)
	$(call check_command,docker-compose,docker-compose)
	$(call log_success,All requirements are met.)

install-node:
	$(call log_info,Installing NPM dependencies...)
	@if [ -f "$(WEB_PATH)/astro-site/package.json" ]; then \
	  cd $(WEB_PATH)/astro-site && npm install && npm audit fix; \
	fi
	$(call log_success,NPM dependencies installed for WEB.)

install-ruby:
	$(call log_info,Installing Ruby and Bundler dependencies...)
	@if [ -f "$(BLOG_PATH)/jekyll-site/Gemfile" ]; then \
	  cd $(BLOG_PATH)/jekyll-site && bundle install && bundle exec jekyll build; \
	fi
	$(call log_success,Bundler dependencies installed for BLOG.)

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

create-network:
	$(call log_info,Creating Docker network if it does not exist...)
	@docker network inspect proxy >/dev/null 2>&1 || docker network create proxy >/dev/null
	$(call log_success,Docker network created or already exists.)

#################################################################################################
# Cleanup commands
#################################################################################################

up-traefik: create-network generate-traefik-config
	$(call log_info,Starting Traefik...)
	@grep -qxF 'ENVIRONMENT=local' $(TRAEFIK_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(TRAEFIK_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(TRAEFIK_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for Traefik started successfully. Remember to add traefik.mlorentedev.test to your /etc/hosts file.)
	$(call log_success,Traefik is running on port 8080. You can access the dashboard at http://traefik.mlorentedev.test/dashboard/)

up-portainer: up-traefik
	$(call log_info,Starting Portainer...)
	@docker compose -f $(PORTAINER_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for Portainer started successfully. Remember to add portainer.mlorentedev.test to your /etc/hosts file.)
	$(call log_success,Portainer is running on port 9000. You can access it at http://portainer.mlorentedev.test)

up-nginx: up-traefik
	$(call log_info,Starting Nginx...)
	@docker compose -f $(NGINX_PATH)/docker-compose.yml up -d
	$(call log_success,Nginx is served on port 80.)

up-n8n: up-traefik
	$(call log_info,Starting N8N...)
	@grep -qxF 'ENVIRONMENT=local' $(N8N_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(N8N_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(N8N_PATH)//docker-compose.yml up -d
	$(call log_success,Development environment for N8N started successfully. Remember to add n8n.mlorentedev.test to your /etc/hosts file.)
	$(call log_success,N8N is running on port 5678. You can access it at http://n8n.mlorentedev.test)

up-monitoring: up-traefik
	$(call log_info,Starting Monitoring stack...)
	@grep -qxF 'ENVIRONMENT=local' $(MONITORING_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(MONITORING_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(MONITORING_PATH)/docker-compose.yml up -d 
	$(call log_success,Development environment for Monitoring started successfully. Remember to add grafana.mlorentedev.test, loki.mlorentedev.test and status.mlorentedev.test to your /etc/hosts file.)
	$(call log_success,Grafana is running on port 3000. You can access it at http://grafana.mlorentedev.test)
	$(call log_success,Loki is running on port 3100. You can access it at http://loki.mlorentedev.test)
	$(call log_success,Status page is running on port 8000. You can access it at http://status.mlorentedev.test)

up-blog: up-traefik
	$(call log_info,Starting local development environment for BLOG...)
	@grep -qxF 'ENVIRONMENT=local' $(BLOG_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(BLOG_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for BLOG started successfully. Remember to add blog.mlorentedev.test to your /etc/hosts file.)
	${call log_success,BLOG is running on port 4000. You can access it at http://blog.mlorentedev.test}

up-web: up-traefik
	$(call log_info,Starting local development environment for WEB...)
	@grep -qxF 'ENVIRONMENT=local' $(WEB_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(WEB_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(WEB_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(WEB_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for WEB started successfully. Remember to add site.mlorentedev.test to your /etc/hosts file.)	
	$(call log_success,WEB is running on port 4321. You can access it at http://site.mlorentedev.test)

up-api: up-traefik
	$(call log_info,Starting local development environment for API...)
	@grep -qxF 'ENVIRONMENT=local' $(API_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(API_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(API_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(API_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for API started successfully. Remember to add api.mlorentedev.test to your /etc/hosts file.)
	$(call log_success,API is running on port 8080. You can access it at http://api.mlorentedev.test/api)

up: check up-traefik up-portainer up-nginx up-blog up-api up-web up-n8n up-monitoring

################################################################################################
# Deployment commands
################################################################################################

setup: check
	$(call log_info,Setting up $(ENVIRONMENT) environment...)
	@if [ ! -f "$(ANSIBLE_PATH)/inventories/hosts.yml" ]; then \
		$(call log_error,Inventory file $(ANSIBLE_PATH)/inventories/hosts.yml not found); \
		exit 1; \
	fi
	ansible-playbook $(ANSIBLE_PATH)/playbooks/setup.yml -i $(ANSIBLE_PATH)/inventories/hosts.yml --limit $(ENVIRONMENT) -e "env=$(ENVIRONMENT)" --private-key $(SSH_KEY) --ask-become-pass -v

deploy: check generate-config
	$(call log_info,Deploying to $(ENVIRONMENT)...)
	ansible-playbook $(PLAYBOOK_PATH)/deploy.yml -i $(INVENTORY) --limit $(ENVIRONMENT) -e "env=$(ENVIRONMENT)" --private-key $(SSH_KEY) --ask-become-pass -v

status: check
	$(call log_info,Checking status in $(ENVIRONMENT)...)
	ansible $(ENVIRONMENT) -i $(INVENTORY) -m shell -a "docker ps"

##################################################################################################
# Utility commands
##################################################################################################

down-traefik:
	$(call log_info,Cleaning Traefik resources...)
	-@docker compose -f $(TRAEFIK_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,Traefik resources cleaned.)

down-portainer:
	$(call log_info,Cleaning Portainer resources...)
	-@docker compose -f $(PORTAINER_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,Portainer resources cleaned.)

down-nginx:
	$(call log_info,Cleaning Nginx resources...)
	-@docker compose -f $(NGINX_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,Nginx resources cleaned.)

down-n8n:
	$(call log_info,Cleaning N8N resources...)
	-@docker compose -f $(N8N_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,N8N resources cleaned.)

down-monitoring:
	$(call log_info,Cleaning Monitoring resources...)
	-@docker compose -f $(MONITORING_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,Monitoring resources cleaned.)

down-web:
	$(call log_info,Cleaning WEB resources...)
	-@docker compose -f $(WEB_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,WEB resources cleaned.)

down-blog:
	$(call log_info,Cleaning BLOG resources...)
	-@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,BLOG resources cleaned.)

down-api:
	$(call log_info,Cleaning API resources...)
	-@docker compose -f $(API_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,API resources cleaned.)

down: down-traefik down-web down-blog down-api down-n8n down-monitoring down-nginx down-portainer
	@docker volume prune -f
	$(call log_success,Local resources cleaned.)

##################################################################################################
# Utility commands
##################################################################################################

generate-config: generate-traefik-credentials generate-traefik-config generate-ansible-config

generate-traefik-credentials:
	$(call log_info,Generating authentication credentials for Traefik...)
	@chmod +x $(SCRIPTS_PATH)/generate-traefik-credentials.sh
	@$(SCRIPTS_PATH)/generate-traefik-credentials.sh
	$(call log_success,Credentials successfully generated.)

generate-traefik-config:
	$(call log_info,Generating Traefik configuration files from templates...)
	@chmod +x $(SCRIPTS_PATH)/generate-traefik-config.sh
	@$(SCRIPTS_PATH)/generate-traefik-config.sh
	$(call log_success,Configuration files generated successfully.)

generate-ansible-config:
	$(call log_info,Generating Ansible configuration files from templates...)
	@chmod +x $(SCRIPTS_PATH)/generate-ansible-config.sh
	@$(SCRIPTS_PATH)/generate-ansible-config.sh
	$(call log_success,Ansible configuration files generated successfully.)

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

create-env-example: 
	$(call log_info,Creating .env.example file...)
	@chmod +x $(SCRIPTS_PATH)/create-env-example.sh
	@$(SCRIPTS_PATH)/create-env-example.sh $(WEB_PATH)/.env $(WEB_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(BLOG_PATH)/.env $(BLOG_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(API_PATH)/.env $(API_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(TRAEFIK_PATH)/.env $(TRAEFIK_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(N8N_PATH)/.env $(N8N_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(MONITORING_PATH)/.env $(MONITORING_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(ANSIBLE_PATH)/.env $(ANSIBLE_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(PORTAINER_PATH)/.env $(PORTAINER_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(NGINX_PATH)/.env $(NGINX_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh .env .env.example
	$(call log_success,.env.example files created successfully.)

setup-secrets: 
	$(call log_info,Setting up GitHub secrets...)
	@chmod +x $(SCRIPTS_PATH)/setup-gh-secrets.sh
	@if [ -f ".env" ]; then \
	    $(SCRIPTS_PATH)/setup-gh-secrets.sh .env; \
	elif [ -f "../.env" ]; then \
        $(SCRIPTS_PATH)/setup-gh-secrets.sh ../.env; \
	else \
	    $(SCRIPTS_PATH)/setup-gh-secrets.sh; \
	fi

list-secrets:
	$(call log_info,Listing GitHub secrets...)
	@gh secret list

###########################################################################################
# Pipeline testing commands
###########################################################################################

validate-yaml:
	@echo "$(GREEN)Validating YAML files...$(NC)"
	@find .github/workflows -name "*.yml" -exec yamllint {} \;

lint-workflows:
	@echo "$(GREEN)Linting workflows...$(NC)"
	@actionlint .github/workflows/*.yml