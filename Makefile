SHELL := /bin/zsh
.SHELLFLAGS := -c -l

export ENVIRONMENT=dev

ifneq (,$(wildcard .env.$(ENVIRONMENT)))
  include .env.$(ENVIRONMENT)
  export
endif

ifneq (,$(wildcard infra/traefik/.env.$(ENVIRONMENT)))
  include infra/traefik/.env.$(ENVIRONMENT)
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

.PHONY: help check install-precommit-hooks install-deps install-ansible create-network \
		up-traefik up-n8n up-grafana up-loki up-uptime up-blog up-web up-api up-wiki up-minio up \
		setup deploy status down down-traefik down-n8n down-grafana down-loki down-uptime down-web down-blog down-api down-wiki down-minio down \
		generate-config generate-credentials generate-traefik-config generate-ansible-config copy-certificates generate-env-example setup-secrets list-secrets \
		validate-yaml lint-workflows \
		setup-buildx docker-login push-app push-app-tag push-all push-all-tag \
		pull-images clean-images list-images help-docker

help:
	$(call log_info,Installation and setup commands:)
	@echo "  make check                			- Check prerequisites"
	@echo "  make install-precommit-hooks           			- Set up environment tools"
	@echo "  make install-node	   				- Install NPM dependencies for WEB"
	@echo "  make install-ruby         			- Install Ruby and Bundler dependencies for BLOG"
	@echo "  make install-ansible      			- Install Ansible and dependencies"
	@echo "  make create-network       			- Create Docker network if it does not exist"
	$(call log_info,Server deployment commands:)
	@echo "  make setup               			- Initial setup for the environment"
	@echo "  make deploy              			- Deploy application to the environment"
	@echo "  make status              			- View service status in the environment"
	$(call log_info,Utility commands:)
	@echo "  make generate-config     			- Generate all configuration files from templates"
	@echo "  make generate-credentials 			- Generate authentication credentials for all apps"
	@echo "  make generate-traefik-config 		- Generate Traefik configuration files from templates"
	@echo "  make generate-ansible-config 		- Generate Ansible configuration files from templates"
	@echo "  make copy-certificates   			- Copy self-signed SSL certificates to the in the local machine"
	@echo "  make setup-secrets       			- Configure GitHub secrets from .env files"
	@echo "  make list-secrets        			- List configured GitHub secrets"
	@echo "  make generate-env-example  			- Create .env.example from .env files"
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

install-precommit-hooks:
	$(call log_info,Setting up environment tools...)
	@chmod +x $(SCRIPTS_PATH)/install-precommit-hooks.sh
	@$(SCRIPTS_PATH)/install-precommit-hooks.sh
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
# Main commands
#################################################################################################

up-traefik: create-network generate-traefik-config
	$(call log_info,Starting $(APP_TRAEFIK_NAME)...)
	@docker compose --env-file $(TRAEFIK_PATH)/.env.$(ENVIRONMENT) -f $(TRAEFIK_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_TRAEFIK_NAME) started successfully. Remember to add $(TRAEFIK_DASHBOARD_HOST) to /etc/hosts file or DNS.)
	$(call log_success,$(APP_TRAEFIK_NAME) service is running on port $(APP_TRAEFIK_PORT). You can access the dashboard at http://$(TRAEFIK_DASHBOARD_HOST)/dashboard/)

up-nginx: up-traefik
	$(call log_info,Starting Nginx...)
	@docker compose --env-file $(NGINX_PATH)/.env.$(ENVIRONMENT) -f $(NGINX_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for Nginx started successfully.)
	$(call log_success,Nginx service is served on port 80.)

up-portainer: up-traefik
	$(call log_info,Starting $(APP_PORTAINER_NAME)...)
	@docker compose --env-file $(PORTAINER_PATH)/.env.$(ENVIRONMENT) -f $(PORTAINER_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_PORTAINER_NAME) started successfully. Remember to add $(APP_PORTAINER_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_PORTAINER_NAME) service is running on port $(APP_PORTAINER_PORT). You can access it at http://$(APP_PORTAINER_HOST))

up-n8n: up-traefik
	$(call log_info,Starting $(APP_N8N_NAME)...)
	@docker compose --env-file $(N8N_PATH)/.env.$(ENVIRONMENT) -f $(N8N_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_N8N_NAME) started successfully. Remember to add $(APP_N8N_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_N8N_NAME) service is running on port $(APP_N8N_PORT). You can access it at http://$(APP_N8N_HOST))

up-grafana: up-traefik
	$(call log_info,Starting $(APP_GRAFANA_NAME)...)
	@docker compose --env-file $(GRAFANA_PATH)/.env.$(ENVIRONMENT) -f $(GRAFANA_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_GRAFANA_NAME) started successfully. Remember to add $(APP_GRAFANA_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_GRAFANA_NAME) service is running on port $(APP_GRAFANA_PORT). You can access it at http://$(APP_GRAFANA_HOST))

up-loki: up-traefik
	$(call log_info,Starting $(APP_LOKI_NAME)...)
	@docker compose --env-file $(LOKI_PATH)/.env.$(ENVIRONMENT) -f $(LOKI_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_LOKI_NAME) started successfully. Remember to add $(APP_LOKI_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_LOKI_NAME) service is running on port $(APP_LOKI_PORT). You can access it at http://$(APP_LOKI_HOST))

up-uptime: up-traefik
	$(call log_info,Starting $(APP_UPTIME_KUMA_NAME)...)
	@docker compose --env-file $(UPTIME_PATH)/.env.$(ENVIRONMENT) -f $(UPTIME_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_UPTIME_KUMA_NAME) started successfully. Remember to add $(APP_UPTIME_KUMA_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_UPTIME_KUMA_NAME) service is running on port $(APP_UPTIME_KUMA_PORT). You can access it at http://$(APP_UPTIME_KUMA_HOST))

up-blog: up-traefik
	$(call log_info,Starting $(ENVIRONMENT) environment for $(APP_BLOG_NAME)...)
	@docker compose --env-file $(BLOG_PATH)/.env.$(ENVIRONMENT) -f $(BLOG_PATH)/docker-compose.$(ENVIRONMENT).yml build --no-cache
	@docker compose --env-file $(BLOG_PATH)/.env.$(ENVIRONMENT) -f $(BLOG_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_BLOG_NAME) started successfully. Remember to add $(APP_BLOG_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_BLOG_NAME) service is running on port $(APP_BLOG_PORT). You can access it at http://$(APP_BLOG_HOST))

up-web: up-traefik
	$(call log_info,Starting $(ENVIRONMENT) environment for $(APP_WEB_NAME)...)
	@docker compose --env-file $(WEB_PATH)/.env.$(ENVIRONMENT) -f $(WEB_PATH)/docker-compose.$(ENVIRONMENT).yml build --no-cache
	@docker compose --env-file $(WEB_PATH)/.env.$(ENVIRONMENT) -f $(WEB_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_WEB_NAME) started successfully. Remember to add $(APP_WEB_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_WEB_NAME) service is running on port $(APP_WEB_PORT). You can access it at http://$(APP_WEB_HOST))

up-api: up-traefik
	$(call log_info,Starting $(ENVIRONMENT) environment for $(APP_API_NAME)...)
	@docker compose --env-file $(API_PATH)/.env.$(ENVIRONMENT) -f $(API_PATH)/docker-compose.$(ENVIRONMENT).yml build --no-cache
	@docker compose --env-file $(API_PATH)/.env.$(ENVIRONMENT) -f $(API_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_API_NAME) started successfully. Remember to add $(APP_API_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_API_NAME) serviceis running on port $(APP_API_PORT). You can access it at http://$(APP_API_HOST)/api)

up-wiki:  wiki-sync up-traefik
	$(call log_info,Starting $(ENVIRONMENT) environment for $(APP_WIKI_NAME)...)
	@docker compose --env-file $(WIKI_PATH)/.env.$(ENVIRONMENT) -f $(WIKI_PATH)/docker-compose.$(ENVIRONMENT).yml build --no-cache
	@docker compose --env-file $(WIKI_PATH)/.env.$(ENVIRONMENT) -f $(WIKI_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_WIKI_NAME) started successfully. Remember to add $(APP_WIKI_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_WIKI_NAME) service is running on port $(APP_WIKI_PORT). You can access it at http://$(APP_WIKI_HOST))

up-minio: up-traefik
	$(call log_info,Starting $(APP_MINIO_NAME)...)
	@docker compose --env-file $(MINIO_PATH)/.env.$(ENVIRONMENT) -f $(MINIO_PATH)/docker-compose.$(ENVIRONMENT).yml up -d
	$(call log_success,$(ENVIRONMENT) environment for $(APP_MINIO_NAME) started successfully. Remember to add $(APP_MINIO_DASHBOARD_HOST) to your /etc/hosts file or DNS.)
	$(call log_success,$(APP_MINIO_NAME) is running on port $(APP_MINIO_API_PORT). API is accessible at http://$(APP_MINIO_API_HOST))
	$(call log_success,$(APP_MINIO_NAME) dashboard service is running on port $(APP_MINIO_DASHBOARD_PORT). You can access it at http://$(APP_MINIO_DASHBOARD_HOST))

up: check up-traefik up-portainer up-nginx up-blog up-api up-web up-n8n up-loki up-uptime up-grafana up-wiki up-minio

##################################################################################################
# Cleanup commands
##################################################################################################

down-traefik:
	$(call log_info,Cleaning $(APP_TRAEFIK_NAME) resources...)
	-@docker compose --env-file $(TRAEFIK_PATH)/.env.$(ENVIRONMENT) -f $(TRAEFIK_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_TRAEFIK_NAME) resources cleaned.)

down-portainer:
	$(call log_info,Cleaning $(APP_PORTAINER_NAME) resources...)
	-@docker compose --env-file $(PORTAINER_PATH)/.env.$(ENVIRONMENT) -f $(PORTAINER_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_PORTAINER_NAME) resources cleaned.)

down-nginx:
	$(call log_info,Cleaning Nginx resources...)
	-@docker compose --env-file $(NGINX_PATH)/.env.$(ENVIRONMENT) -f $(NGINX_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,Nginx resources cleaned.)

down-n8n:
	$(call log_info,Cleaning $(APP_N8N_NAME) resources...)
	-@docker compose --env-file $(N8N_PATH)/.env.$(ENVIRONMENT) -f $(N8N_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_N8N_NAME) resources cleaned.)

down-grafana:
	$(call log_info,Cleaning $(APP_GRAFANA_NAME) resources...)
	-@docker compose --env-file $(GRAFANA_PATH)/.env.$(ENVIRONMENT) -f $(GRAFANA_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_GRAFANA_NAME) resources cleaned.)

down-loki:
	$(call log_info,Cleaning $(APP_LOKI_NAME) resources...)
	-@docker compose --env-file $(LOKI_PATH)/.env.$(ENVIRONMENT) -f $(LOKI_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_LOKI_NAME) resources cleaned.)

down-uptime:
	$(call log_info,Cleaning $(APP_UPTIME_KUMA_NAME) resources...)
	-@docker compose --env-file $(UPTIME_PATH)/.env.$(ENVIRONMENT) -f $(UPTIME_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_UPTIME_KUMA_NAME) resources cleaned.)

down-web:
	$(call log_info,Cleaning $(APP_WEB_NAME) resources...)
	-@docker compose --env-file $(WEB_PATH)/.env.$(ENVIRONMENT) -f $(WEB_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_WEB_NAME) resources cleaned.)

down-blog:
	$(call log_info,Cleaning $(APP_BLOG_NAME) resources...)
	-@docker compose --env-file $(BLOG_PATH)/.env.$(ENVIRONMENT) -f $(BLOG_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_BLOG_NAME) resources cleaned.)

down-api:
	$(call log_info,Cleaning $(APP_API_NAME) resources...)
	-@docker compose --env-file $(API_PATH)/.env.$(ENVIRONMENT) -f $(API_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_API_NAME) resources cleaned.)

down-wiki:
	$(call log_info,Cleaning $(APP_WIKI_NAME) resources...)
	-@docker compose --env-file $(WIKI_PATH)/.env.$(ENVIRONMENT) -f $(WIKI_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_WIKI_NAME) resources cleaned.)

down-minio:
	$(call log_info,Cleaning $(APP_MINIO_NAME) resources...)
	-@docker compose --env-file $(MINIO_PATH)/.env.$(ENVIRONMENT) -f $(MINIO_PATH)/docker-compose.$(ENVIRONMENT).yml down --remove-orphans
	$(call log_success,$(APP_MINIO_NAME) resources cleaned.)

down: down-traefik down-web down-blog down-api down-n8n down-grafana down-loki down-uptime down-nginx down-portainer down-wiki down-minio
	@docker volume prune -f
	$(call log_success,All resources cleaned.)


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

generate-config: generate-credentials generate-traefik-config generate-ansible-config

generate-credentials:
	$(call log_info,Generating authentication credentials for Traefik...)
	@chmod +x $(SCRIPTS_PATH)/generate-credentials.sh
	@$(SCRIPTS_PATH)/generate-credentials.sh
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

generate-env-example: 
	$(call log_info,Creating .env.example file...)
	@chmod +x $(SCRIPTS_PATH)/generate-env-example.sh
	@$(SCRIPTS_PATH)/generate-env-example.sh $(TRAEFIK_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(TRAEFIK_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(ANSIBLE_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(NGINX_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(NGINX_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(WEB_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(WEB_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(BLOG_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(BLOG_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(API_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(API_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(N8N_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(N8N_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(GRAFANA_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(GRAFANA_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(LOKI_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(LOKI_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(UPTIME_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(UPTIME_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(PORTAINER_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(PORTAINER_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(WIKI_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(WIKI_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh $(MINIO_PATH)/.env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh $(MINIO_PATH)/.env.prod
	@$(SCRIPTS_PATH)/generate-env-example.sh .env.dev
	@$(SCRIPTS_PATH)/generate-env-example.sh .env.prod
	$(call log_success,.env.example files created successfully.)


setup-secrets: 
	$(call log_info,Setting up GitHub secrets...)
	@chmod +x $(SCRIPTS_PATH)/setup-gh-secrets.sh
	@if [ -f ".env.prod" ]; then \
	    $(SCRIPTS_PATH)/setup-gh-secrets.sh .env.prod; \
	elif [ -f "../.env.prod" ]; then \
        $(SCRIPTS_PATH)/setup-gh-secrets.sh ../.env.prod; \
	else \
	    $(SCRIPTS_PATH)/setup-gh-secrets.sh; \
	fi

list-secrets:
	$(call log_info,Listing GitHub secrets...)
	@gh secret list

wiki-sync:
	$(call log_info,Generating wiki documentation...)
	@$(SCRIPTS_PATH)/generate-wiki.sh build

###########################################################################################
# Pipeline testing commands
###########################################################################################

validate-yaml:
	@echo "$(GREEN)Validating YAML files...$(NC)"
	@find .github/workflows -name "*.yml" -exec yamllint {} \;

lint-workflows:
	@echo "$(GREEN)Linting workflows...$(NC)"
	@actionlint .github/workflows/*.yml