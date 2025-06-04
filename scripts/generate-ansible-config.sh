#!/bin/bash
# ansible-config-with-traefik-auth.sh

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANSIBLE_DIR="$PROJECT_ROOT/deployment/ansible"
TEMPLATES_DIR="$ANSIBLE_DIR/templates"
INVENTORY_DIR="$ANSIBLE_DIR/inventory"
GROUP_VARS_DIR="$INVENTORY_DIR/group_vars"

# Load environment variables from .env file if it exists
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"
[ -f "$PROJECT_ROOT/.env" ] && source "$PROJECT_ROOT/.env"

# Check if .env is sourced
required_vars=("DOMAIN" "STAGING_DOMAIN" "PRODUCTION_DOMAIN")
if ! verify_required_vars "${required_vars[@]}"; then
    exit 1
fi

# Create directories if they don't exist
mkdir -p "$INVENTORY_DIR" "$GROUP_VARS_DIR"

# Ensure templates directory exists
if [ ! -d "$TEMPLATES_DIR" ]; then
    log_error "Error: Templates directory not found: $TEMPLATES_DIR"
    exit 1
fi

# Generate Ansible configuration files
log_info "Generating Ansible configuration files..."

# Process hosts.yml file
if [ -f "$TEMPLATES_DIR/hosts.template.yml" ]; then
    replace_placeholders "$TEMPLATES_DIR/hosts.template.yml" "$INVENTORY_DIR/hosts.yml"
    log_success "Generated: $INVENTORY_DIR/hosts.yml"
fi

# Process group_vars
if [ -d "$TEMPLATES_DIR/group_vars" ]; then
    log_info "Processing group_vars templates..."
    
    for template_file in "$TEMPLATES_DIR/group_vars"/*.template.yml; do
        [ ! -f "$template_file" ] && continue
        
        base_name=$(basename "$template_file" .template.yml)
        output_file="$GROUP_VARS_DIR/$base_name.yml"
        
        log_info "Processing group_vars template: $(basename "$template_file")"
        
        if replace_placeholders "$template_file" "$output_file"; then
            log_success "Generated: $output_file"
        else
            log_error "Failed to generate: $output_file"
        fi
    done
fi

# Process additional template files
log_info "Processing additional template files..."

for template_file in "$TEMPLATES_DIR"/*.template.yml; do
    [ ! -f "$template_file" ] && continue
    
    # Saltar hosts.template.yml ya procesado
    [ "$(basename "$template_file")" = "hosts.template.yml" ] && continue
    
    base_name=$(basename "$template_file" .template.yml)
    
    # Determinar si es un archivo group_vars o inventario regular
    if [[ "$base_name" == *_vars ]]; then
        group_name=${base_name%_vars}
        output_file="$GROUP_VARS_DIR/$group_name.yml"
    else
        output_file="$INVENTORY_DIR/$base_name.yml"
    fi
    
    log_info "Processing template: $(basename "$template_file")"
    
    if replace_placeholders "$template_file" "$output_file"; then
        log_success "Generated: $output_file"
    else
        log_error "Failed to generate: $output_file"
    fi
done

log_success "Ansible configuration generated successfully."
log_info "Configuration files are located in: $ANSIBLE_DIR"
log_info "Inventory file: $INVENTORY_DIR/hosts.yml"
log_info "Group variables: $GROUP_VARS_DIR/"
log_info "To apply these configurations, run your Ansible playbooks with this inventory."