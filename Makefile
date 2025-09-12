# Makefile for mlorente.dev management
SHELL := /bin/zsh
.SHELLFLAGS := -c -l

ifneq (,$(wildcard .env))
  include .env
  include infra/traefik/.env
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

.PHONY: help check env-setup install-deps install-ansible create-network \
		up-traefik up-n8n up-grafana up-loki up-uptime up-blog up-web up-api up-wiki up-minio up \
		setup deploy status down down-traefik down-n8n down-grafana down-loki down-uptime down-web down-blog down-api down-wiki down-minio down \
		generate-config generate-traefik-credentials generate-traefik-config generate-ansible-config copy-certificates create-env-example setup-secrets list-secrets \
		validate-yaml lint-workflows \
		setup-buildx docker-login push-app push-app-tag push-all push-all-tag \
		pull-images clean-images list-images help-docker

help:
	$(call log_info,Installation and setup commands:)
	@echo "  make check                			- Check prerequisites"
	@echo "  make env-setup           			- Set up environment tools"
	@echo "  make install-node	   				- Install NPM dependencies for WEB"
	@echo "  make install-ruby         			- Install Ruby and Bundler dependencies for BLOG"
	@echo "  make install-ansible      			- Install Ansible and dependencies"
	@echo "  make create-network       			- Create Docker network if it does not exist"
	$(call log_info,Docker build and push commands:)
	@echo "  make docker-login         			- Login to Docker registry"
	@echo "  make push-app APP=<app>   			- Build and push specific app"
	@echo "  make push-app-tag APP=<app> TAG=<tag>		- Build and push app with specific tag"
	@echo "  make push-all             			- Build and push all apps"
	@echo "  make push-all-tag TAG=<tag>			- Build and push all apps with tag"
	@echo "  make pull-images          			- Pull latest images from registry"
	@echo "  make clean-images         			- Clean local Docker images"
	@echo "  make list-images          			- List local Docker images"
	$(call log_info,Server deployment commands:)
	@echo "  make setup               			- Initial setup for the environment"
	@echo "  make deploy              			- Deploy application to the environment"
	@echo "  make status              			- View service status in the environment"
	$(call log_info,Utility commands:)
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
	$(call check_command,perl,perl)
	$(call log_success,All requirements are met.)

env-setup:
	$(call log_info,Setting up environment tools...)
	@chmod +x $(SCRIPTS_PATH)/env-setup.sh
	@$(SCRIPTS_PATH)/env-setup.sh
	$(call log_success,Environment tools set up successfully.)

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
# Development commands
#################################################################################################

up-traefik: create-network generate-traefik-config
	$(call log_info,Starting Traefik...)
	@grep -qxF 'ENVIRONMENT=local' $(TRAEFIK_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(TRAEFIK_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(TRAEFIK_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_TRAEFIK_NAME) started successfully. Remember to add $(TRAEFIK_DASHBOARD_HOST) to your /etc/hosts file.)
	$(call log_success,Traefik is running on port $(APP_TRAEFIK_PORT). You can access the dashboard at http://$(TRAEFIK_DASHBOARD_HOST)/dashboard/)

up-portainer: up-traefik
	$(call log_info,Starting Portainer...)
	@grep -qxF 'ENVIRONMENT=local' $(PORTAINER_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(PORTAINER_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(PORTAINER_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_PORTAINER_NAME) started successfully. Remember to add $(APP_PORTAINER_HOST) to your /etc/hosts file.)
	$(call log_success,Portainer is running on port $(APP_PORTAINER_PORT). You can access it at http://$(APP_PORTAINER_HOST))

up-nginx: up-traefik
	$(call log_info,Starting Nginx...)
	@grep -qxF 'ENVIRONMENT=local' $(NGINX_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(NGINX_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(NGINX_PATH)/docker-compose.yml up -d
	$(call log_success,Nginx is served on port 80.)

up-n8n: up-traefik
	$(call log_info,Starting N8N...)
	@grep -qxF 'ENVIRONMENT=local' $(N8N_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(N8N_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(N8N_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_N8N_NAME) started successfully. Remember to add $(APP_N8N_HOST) to your /etc/hosts file.)
	$(call log_success,N8N is running on port $(APP_N8N_PORT). You can access it at http://$(APP_N8N_HOST))

up-grafana: up-traefik
	$(call log_info,Starting Grafana...)
	@grep -qxF 'ENVIRONMENT=local' $(GRAFANA_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(GRAFANA_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(GRAFANA_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_GRAFANA_NAME) started successfully. Remember to add $(APP_GRAFANA_HOST) to your /etc/hosts file.)
	$(call log_success,Grafana is running on port $(APP_GRAFANA_PORT). You can access it at http://$(APP_GRAFANA_HOST))

up-loki: up-traefik
	$(call log_info,Starting Loki...)
	@grep -qxF 'ENVIRONMENT=local' $(LOKI_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(LOKI_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(LOKI_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_LOKI_NAME) started successfully. Remember to add $(APP_LOKI_HOST) to your /etc/hosts file.)
	$(call log_success,Loki is running on port $(APP_LOKI_PORT). You can access it at http://$(APP_LOKI_HOST))

up-uptime: up-traefik
	$(call log_info,Starting Uptime Kuma...)
	@grep -qxF 'ENVIRONMENT=local' $(UPTIME_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(UPTIME_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(UPTIME_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_UPTIME_KUMA_NAME) started successfully. Remember to add $(APP_UPTIME_KUMA_HOST) to your /etc/hosts file.)
	$(call log_success,Status page is running on port $(APP_UPTIME_KUMA_PORT). You can access it at http://$(APP_UPTIME_KUMA_HOST))

up-blog: up-traefik
	$(call log_info,Starting local development environment for BLOG...)
	@grep -qxF 'ENVIRONMENT=local' $(BLOG_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(BLOG_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for $(APP_BLOG_NAME) started successfully. Remember to add $(APP_BLOG_HOST) to your /etc/hosts file.)
	$(call log_success,BLOG is running on port $(APP_BLOG_PORT). You can access it at http://$(APP_BLOG_HOST))

up-web: up-traefik
	$(call log_info,Starting local development environment for WEB...)
	@grep -qxF 'ENVIRONMENT=local' $(WEB_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(WEB_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(WEB_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(WEB_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for $(APP_WEB_NAME) started successfully. Remember to add $(APP_WEB_HOST) to your /etc/hosts file.)
	$(call log_success,WEB is running on port $(APP_WEB_PORT). You can access it at http://$(APP_WEB_HOST))

up-api: up-traefik
	$(call log_info,Starting local development environment for API...)
	@grep -qxF 'ENVIRONMENT=local' $(API_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(API_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(API_PATH)/docker-compose.dev.yml build --no-cache
	@docker compose -f $(API_PATH)/docker-compose.dev.yml up -d
	$(call log_success,Development environment for $(APP_API_NAME) started successfully. Remember to add $(APP_API_HOST) to your /etc/hosts file.)
	$(call log_success,API is running on port $(APP_API_PORT). You can access it at http://$(APP_API_HOST)/api)

up-wiki:  wiki-sync up-traefik
	$(call log_info,Starting local development environment for WIKI...)
	@grep -qxF 'ENVIRONMENT=local' $(WIKI_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(WIKI_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(WIKI_PATH)/docker-compose.yml build --no-cache
	@docker compose -f $(WIKI_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_WIKI_NAME) started successfully. Remember to add $(APP_WIKI_HOST) to your /etc/hosts file.)
	$(call log_success,WIKI is running on port $(APP_WIKI_PORT). You can access it at http://$(APP_WIKI_HOST))

up-minio: up-traefik
	$(call log_info,Starting MinIO...)
	@grep -qxF 'ENVIRONMENT=local' $(MINIO_PATH)/.env || { \
	  $(call log_error,ENVIRONMENT must be set to 'local' in $(MINIO_PATH)/.env); \
	  exit 1; \
	}
	@docker compose -f $(MINIO_PATH)/docker-compose.yml up -d
	$(call log_success,Development environment for $(APP_MINIO_NAME) started successfully. Remember to add $(APP_MINIO_DASHBOARD_HOST) to your /etc/hosts file.)
	$(call log_success,MinIO is running on port $(APP_MINIO_API_PORT). API is accessible at http://$(APP_MINIO_API_HOST))
	$(call log_success,MinIO dashboard is running on port $(APP_MINIO_DASHBOARD_PORT). You can access it at http://$(APP_MINIO_DASHBOARD_HOST))

up: check up-traefik up-portainer up-nginx up-blog up-api up-web up-n8n up-loki up-uptime up-grafana up-wiki up-minio

##################################################################################################
# Cleanup commands
##################################################################################################

down-traefik:
	$(call log_info,Cleaning $(APP_TRAEFIK_NAME) resources...)
	-@docker compose -f $(TRAEFIK_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_TRAEFIK_NAME) resources cleaned.)

down-portainer:
	$(call log_info,Cleaning $(APP_PORTAINER_NAME) resources...)
	-@docker compose -f $(PORTAINER_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_PORTAINER_NAME) resources cleaned.)

down-nginx:
	$(call log_info,Cleaning Nginx resources...)
	-@docker compose -f $(NGINX_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,Nginx resources cleaned.)

down-n8n:
	$(call log_info,Cleaning $(APP_N8N_NAME) resources...)
	-@docker compose -f $(N8N_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_N8N_NAME) resources cleaned.)

down-grafana:
	$(call log_info,Cleaning $(APP_GRAFANA_NAME) resources...)
	-@docker compose -f $(GRAFANA_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_GRAFANA_NAME) resources cleaned.)

down-loki:
	$(call log_info,Cleaning $(APP_LOKI_NAME) resources...)
	-@docker compose -f $(LOKI_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_LOKI_NAME) resources cleaned.)

down-uptime:
	$(call log_info,Cleaning $(APP_UPTIME_KUMA_NAME) resources...)
	-@docker compose -f $(UPTIME_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_UPTIME_KUMA_NAME) resources cleaned.)

down-web:
	$(call log_info,Cleaning $(APP_WEB_NAME) resources...)
	-@docker compose -f $(WEB_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,$(APP_WEB_NAME) resources cleaned.)

down-blog:
	$(call log_info,Cleaning $(APP_BLOG_NAME) resources...)
	-@docker compose -f $(BLOG_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,$(APP_BLOG_NAME) resources cleaned.)

down-api:
	$(call log_info,Cleaning $(APP_API_NAME) resources...)
	-@docker compose -f $(API_PATH)/docker-compose.dev.yml down --remove-orphans
	$(call log_success,$(APP_API_NAME) resources cleaned.)

down-wiki:
	$(call log_info,Cleaning $(APP_WIKI_NAME) resources...)
	-@docker compose -f $(WIKI_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_WIKI_NAME) resources cleaned.)

down-minio:
	$(call log_info,Cleaning $(APP_MINIO_NAME) resources...)
	-@docker compose -f $(MINIO_PATH)/docker-compose.yml down --remove-orphans
	$(call log_success,$(APP_MINIO_NAME) resources cleaned.)

down: down-traefik down-web down-blog down-api down-n8n down-grafana down-loki down-uptime down-nginx down-portainer down-wiki down-minio
	@docker volume prune -f
	$(call log_success,Local resources cleaned.)

##################################################################################################
# Docker Build and Push Commands
##################################################################################################

setup-buildx:
	$(call log_info,Setting up Docker Buildx for multi-architecture builds...)
	@docker buildx create --name multiarch --driver docker-container --use 2>/dev/null || \
		docker buildx use multiarch 2>/dev/null || \
		docker buildx create --name multiarch --driver docker-container --use
	@docker buildx inspect --bootstrap >/dev/null 2>&1
	$(call log_success,Docker Buildx setup completed.)

# Docker login
docker-login:
	$(call log_info,Logging into Docker registry...)
	@echo "$(DOCKERHUB_TOKEN)" | docker login -u "$(DOCKERHUB_USERNAME)" --password-stdin
	$(call log_success,Successfully logged into Docker registry.)

push-app: setup-buildx docker-login
	@if [ -z "$(APP)" ]; then \
		$(call log_error,APP is required. Usage: make push-app APP=blog); \
		exit 1; \
	fi
	$(call log_info,Building and pushing $(APP) [multi-arch]...)
	@if [ ! -f "apps/$(APP)/Dockerfile" ]; then \
		$(call log_error,Dockerfile not found for app: $(APP)); \
		exit 1; \
	fi
	@docker buildx build \
		--platform linux/amd64,linux/arm64 \
		-t $(DOCKERHUB_USERNAME)/mlorente-$(APP):latest \
		--push \
		apps/$(APP)
	$(call log_success,Successfully pushed $(APP).)

push-app-tag: setup-buildx docker-login
	@if [ -z "$(APP)" ] || [ -z "$(TAG)" ]; then \
		$(call log_error,APP and TAG are required. Usage: make push-app-tag APP=blog TAG=v1.0.0); \
		exit 1; \
	fi
	$(call log_info,Building and pushing $(APP):$(TAG) [multi-arch]...)
	@if [ ! -f "apps/$(APP)/Dockerfile" ]; then \
		$(call log_error,Dockerfile not found for app: $(APP)); \
		exit 1; \
	fi
	@docker buildx build \
		--platform linux/amd64,linux/arm64 \
		-t $(DOCKERHUB_USERNAME)/mlorente-$(APP):$(TAG) \
		-t $(DOCKERHUB_USERNAME)/mlorente-$(APP):latest \
		--push \
		apps/$(APP)
	$(call log_success,Successfully pushed $(APP):$(TAG).)

# Build all application images
build-image:
	@if [ -z "$(APP)" ]; then \
		$(call log_error,APP is required. Usage: make build-image APP=blog); \
		exit 1; \
	fi
	$(call log_info,Building image for $(APP)...)
	@if [ ! -f "apps/$(APP)/Dockerfile" ]; then \
		$(call log_error,Dockerfile not found for app: $(APP)); \
		exit 1; \
	fi
	@docker build -t $(DOCKERHUB_USERNAME)/mlorente-$(APP):latest apps/$(APP)
	$(call log_success,Successfully built image for $(APP).)	
	
build-all-images:
	$(call log_info,Building all application images...)
	@$(MAKE) build-image APP=api
	@$(MAKE) build-image APP=blog
	@$(MAKE) build-image APP=web
	@$(MAKE) build-image APP=wiki
	$(call log_success,Successfully built all application images.)

# Build and push all apps
push-all: setup-buildx docker-login
	$(call log_info,Building and pushing all apps [multi-arch]...)
	@$(MAKE) push-app APP=api
	@$(MAKE) push-app APP=blog
	@$(MAKE) push-app APP=web
	@$(MAKE) push-app APP=wiki
	$(call log_success,Successfully pushed all apps.)

# Build and push all apps with specific tag
push-all-tag: setup-buildx docker-login
	@if [ -z "$(TAG)" ]; then \
		$(call log_error,TAG is required. Usage: make push-all-tag TAG=v1.0.0); \
		exit 1; \
	fi
	$(call log_info,Building and pushing all apps with tag $(TAG) [multi-arch]...)
	@$(MAKE) push-app-tag APP=api TAG=$(TAG)
	@$(MAKE) push-app-tag APP=blog TAG=$(TAG)
	@$(MAKE) push-app-tag APP=web TAG=$(TAG)
	@$(MAKE) push-app-tag APP=wiki TAG=$(TAG)
	$(call log_success,Successfully pushed all apps with tag $(TAG).)

pull-images:
	$(call log_info,Pulling latest images from registry...)
	@docker pull $(DOCKERHUB_USERNAME)/mlorente-api:latest || echo "Failed to pull API image"
	@docker pull $(DOCKERHUB_USERNAME)/mlorente-blog:latest || echo "Failed to pull Blog image"
	@docker pull $(DOCKERHUB_USERNAME)/mlorente-web:latest || echo "Failed to pull Web image"
	@docker pull $(DOCKERHUB_USERNAME)/mlorente-wiki:latest || echo "Failed to pull Wiki image"
	$(call log_success,Finished pulling images.)

clean-images:
	$(call log_info,Cleaning local Docker images...)
	@docker images | grep $(DOCKERHUB_USERNAME)/mlorente- | awk '{print $$3}' | xargs -r docker rmi || true
	$(call log_success,Cleaned local Docker images.)

list-images:
	$(call log_info,Listing local Docker images...)
	@docker images | grep $(DOCKERHUB_USERNAME)/mlorente- || echo "No images found."

################################################################################################
# Deployment commands
################################################################################################

setup: check generate-ansible-config
	$(call log_info,Setting up $(ENVIRONMENT) environment...)
	@if [ ! -f "$(ANSIBLE_PATH)/inventories/hosts.yml" ]; then \
		$(call log_error,Inventory file $(ANSIBLE_PATH)/inventories/hosts.yml not found); \
		exit 1; \
	fi
	ansible-playbook $(ANSIBLE_PATH)/playbooks/setup.yml -i $(ANSIBLE_PATH)/inventories/hosts.yml --limit $(ENVIRONMENT) -e "env=$(ENVIRONMENT)" --private-key $(SSH_KEY)

deploy: check generate-config
	$(call log_info,Deploying to $(ENVIRONMENT)...)
	ansible-playbook $(ANSIBLE_PATH)/playbooks/deploy.yml -i $(ANSIBLE_PATH)/inventories/hosts.yml --limit $(ENVIRONMENT) -e "env=$(ENVIRONMENT)" --private-key $(SSH_KEY)

status: check
	$(call log_info,Checking status in $(ENVIRONMENT)...)
	ansible $(ENVIRONMENT) -i $(ANSIBLE_PATH)/inventories/hosts.yml -m shell -a "docker ps"

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
	@$(SCRIPTS_PATH)/create-env-example.sh $(WIKI_PATH)/.env $(WIKI_PATH)/.env.example
	@$(SCRIPTS_PATH)/create-env-example.sh $(MINIO_PATH)/.env $(MINIO_PATH)/.env.example
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

wiki-sync:
	$(call log_info,Sync README -> docs and build multiversion site...)
	@$(SCRIPTS_PATH)/wiki.sh sync

###########################################################################################
# Pipeline testing commands
###########################################################################################

validate-yaml:
	@echo "$(GREEN)Validating YAML files...$(NC)"
	@find .github/workflows -name "*.yml" -exec yamllint {} \;

lint-workflows:
	@echo "$(GREEN)Linting workflows...$(NC)"
	@actionlint .github/workflows/*.yml