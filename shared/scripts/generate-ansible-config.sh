#!/bin/bash
# ansible-config-with-traefik-auth.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ANSIBLE_DIR="$PROJECT_ROOT/deployment/ansible"
TEMPLATES_DIR="$ANSIBLE_DIR/templates"
INVENTORY_DIR="$ANSIBLE_DIR/inventory"
GROUP_VARS_DIR="$INVENTORY_DIR/group_vars"

# Load environment variables from .env file if it exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"
[ -f "$PROJECT_ROOT/.env" ] && source "$PROJECT_ROOT/.env"

# Check if .env is sourced
if [ -z "$DOMAIN" ]; then
  log_error "Error: .env file not sourced. Please ensure it exists and contains the necessary variables."
  exit 1
fi

# Function to generate basic auth credentials
generate_basic_auth() {
  local username=$1
  local password=$2
  
  # Generate password hash
  if command -v htpasswd > /dev/null; then
    local hashed_password=$(htpasswd -nb "$username" "$password")
    echo "$hashed_password"
  else
    # Fallback to using openssl if htpasswd is not available
    local hashed_password=$(openssl passwd -apr1 "$password")
    echo "${username}:${hashed_password}"
  fi
}

# Function to update environment files with new credentials
update_env_files() {
  local credentials=$1
  
  for env_file in "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.local"; do
    if [ -f "$env_file" ]; then
      # Check if TRAEFIK_DASHBOARD_USERS line exists
      if grep -q "TRAEFIK_DASHBOARD_USERS=" "$env_file"; then
        # Replace existing line in-place
        sed -i "s|TRAEFIK_DASHBOARD_USERS=.*|TRAEFIK_DASHBOARD_USERS=$credentials|" "$env_file"
        log_success "Updated credentials in $env_file"
      else
        # Add the new credentials if line doesn't exist
        echo "TRAEFIK_DASHBOARD_USERS=$credentials" >> "$env_file"
        log_success "Added credentials to $env_file"
      fi
    else
      log_warning "File $env_file doesn't exist, skipping."
    fi
  done

  # Update the current environment variable
  export TRAEFIK_DASHBOARD_USERS="$credentials"
}

# Function to safely replace placeholders
replace_placeholders() {
    local template="$1"
    local output="$2"
    
    # Create a temporary file for processing
    local tmpfile=$(mktemp)
    
    # Copy template to temporary file
    cp "$template" "$tmpfile"

    # Escape slashes in the email address
    escaped_email="${ACME_EMAIL//\//\\/}"
    escaped_email="${escaped_email//@/\\@}"
    escaped_users="${TRAEFIK_DASHBOARD_USERS//$/\\/}"

    # Replace each placeholder with its value
    perl -p -e "s#{{DOCKER_NETWORK}}#${DOCKER_NETWORK}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_DASHBOARD}}#${TRAEFIK_DASHBOARD}#g" -i "$tmpfile"
    perl -p -e "s#{{ARTIFACT_NAME}}#${ARTIFACT_NAME}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_INSECURE}}#${TRAEFIK_INSECURE}#g" -i "$tmpfile"
    perl -p -e "s#{{DISABLE_HTTPS}}#${DISABLE_HTTPS}#g" -i "$tmpfile"
    perl -p -e "s#{{ACME_EMAIL}}#${escaped_email}#g" -i "$tmpfile"
    perl -p -e "s#{{ACME_SERVER}}#${ACME_SERVER//\//\\/}#g" -i "$tmpfile"
    perl -p -e "s#{{TRAEFIK_DASHBOARD_USERS}}#$escaped_users#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_DOMAIN}}#${STAGING_DOMAIN}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_HOST_NAME}}#${STAGING_HOST_NAME}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_HOST_IP}}#${STAGING_HOST_IP}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_HOST_USER}}#${STAGING_HOST_USER}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_HOST_PORT}}#${STAGING_HOST_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{STAGING_DEPLOY_PATH}}#${STAGING_DEPLOY_PATH//\//\\/}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_DOMAIN}}#${PRODUCTION_DOMAIN}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_HOST_NAME}}#${PRODUCTION_HOST_NAME}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_HOST_IP}}#${PRODUCTION_HOST_IP}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_HOST_USER}}#${PRODUCTION_HOST_USER}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_HOST_PORT}}#${PRODUCTION_HOST_PORT}#g" -i "$tmpfile"
    perl -p -e "s#{{PRODUCTION_DEPLOY_PATH}}#${PRODUCTION_DEPLOY_PATH//\//\\/}#g" -i "$tmpfile"

    # Move the processed file to the output location
    mv "$tmpfile" "$output"
}

# Create directories if they don't exist
mkdir -p "$INVENTORY_DIR"
mkdir -p "$GROUP_VARS_DIR"

# Ensure templates directory exists
if [ ! -d "$TEMPLATES_DIR" ]; then
    log_error "Error: Templates directory not found: $TEMPLATES_DIR"
    exit 1
fi

# Generate Traefik dashboard credentials
log_info "Generating Traefik dashboard credentials..."

# Request username
read -p "Enter username for Traefik dashboard (default: admin): " username
username=${username:-admin}

# Request password with confirmation
read -s -p "Enter password: " password
echo
if [ -z "$password" ]; then
  log_error "Password cannot be empty"
  exit 1
fi

# Confirm password
read -s -p "Confirm password: " password_confirm
echo
if [ "$password" != "$password_confirm" ]; then
  log_error "Passwords do not match"
  exit 1
fi

# Generate the credentials
credentials=$(generate_basic_auth "$username" "$password")

# Update .env files
update_env_files "$credentials"
    
log_success "Traefik dashboard credentials generated successfully."
log_info "Username: $username"
log_info "Password: ********"
log_info "Please save these credentials securely."

# Process hosts.yml file
log_info "Generating hosts.yml configuration..."
HOSTS_TEMPLATE="$TEMPLATES_DIR/hosts.template.yml"
if [ -f "$HOSTS_TEMPLATE" ]; then
    replace_placeholders "$HOSTS_TEMPLATE" "$INVENTORY_DIR/hosts.yml"
    log_success "Generated: $INVENTORY_DIR/hosts.yml"
else
    log_error "Error: Template file not found: $HOSTS_TEMPLATE"
fi

# Process all group_vars templates
log_info "Generating group_vars configuration files..."

# Process all.yml
ALL_TEMPLATE="$TEMPLATES_DIR/group_vars/all.template.yml"
if [ -f "$ALL_TEMPLATE" ]; then
    replace_placeholders "$ALL_TEMPLATE" "$GROUP_VARS_DIR/all.yml"
    log_success "Generated: $GROUP_VARS_DIR/all.yml"
else
    log_error "Error: Template file not found: $ALL_TEMPLATE"
fi

# Process production.yml
PRODUCTION_TEMPLATE="$TEMPLATES_DIR/group_vars/production.template.yml"
if [ -f "$PRODUCTION_TEMPLATE" ]; then
    replace_placeholders "$PRODUCTION_TEMPLATE" "$GROUP_VARS_DIR/production.yml"
    log_success "Generated: $GROUP_VARS_DIR/production.yml"
else
    log_error "Error: Template file not found: $PRODUCTION_TEMPLATE"
fi

# Process staging.yml
STAGING_TEMPLATE="$TEMPLATES_DIR/group_vars/staging.template.yml"
if [ -f "$STAGING_TEMPLATE" ]; then
    replace_placeholders "$STAGING_TEMPLATE" "$GROUP_VARS_DIR/staging.yml"
    log_success "Generated: $GROUP_VARS_DIR/staging.yml"
else
    log_error "Error: Template file not found: $STAGING_TEMPLATE"
fi

# Process any additional template files
log_info "Processing additional template files..."

# Loop through all template files in the templates directory
for template_file in "$TEMPLATES_DIR"/*.template.yml; do
    # Skip if file doesn't exist or isn't a regular file
    [ ! -f "$template_file" ] && continue
    
    # Skip the already processed templates
    if [[ "$template_file" == "$HOSTS_TEMPLATE" ]] || [[ "$template_file" == "$ALL_TEMPLATE" ]] || 
       [[ "$template_file" == "$PRODUCTION_TEMPLATE" ]] || [[ "$template_file" == "$STAGING_TEMPLATE" ]]; then
        continue
    fi
    
    # Extract the base filename without path and .template.yml extension
    base_name=$(basename "$template_file" .template.yml)
    
    # Determine output directory and file based on naming convention
    if [[ "$base_name" == *_vars ]]; then
        # This is a group_vars file
        group_name=${base_name%_vars}
        output_file="$GROUP_VARS_DIR/$group_name.yml"
    else
        # This is a regular inventory file
        output_file="$INVENTORY_DIR/$base_name.yml"
    fi
    
    log_info "Processing template: $(basename "$template_file")"
    
    # Process the template
    replace_placeholders "$template_file" "$output_file"
    
    log_success "Generated: $output_file"
done

log_success "Ansible configuration generated successfully."
log_info "Configuration files are located in: $ANSIBLE_DIR"
log_info "Inventory file: $INVENTORY_DIR/hosts.yml"
log_info "Group variables: $GROUP_VARS_DIR/"
log_info "To apply these configurations, run your Ansible playbooks with this inventory."