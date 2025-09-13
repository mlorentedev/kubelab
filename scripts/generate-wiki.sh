#!/bin/zsh
# Generate wiki documentation from mono-repo markdown files
set -euo pipefail
setopt nullglob

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_ROOT="${PROJECT_ROOT}/.env.${ENVIRONMENT:-dev}"
ENV_APP="${PROJECT_ROOT}/apps/wiki/.env.${ENVIRONMENT:-dev}"

source "$SCRIPT_DIR/utils.sh"

# Collect README files from different sections of the mono-repo
collect_documentation() {
  # Default directories
  local apps_source="${APPS_DIR:-apps}"
  local apps_target="${APPS_DOCS_DIR:-apps/wiki/docs/apps}"
  local infra_source="${INFRA_DIR:-infra}"
  local infra_target="${INFRA_DOCS_DIR:-apps/wiki/docs/infra}"
  local guides_source="${GUIDES_DIR:-docs}"
  local guides_target="${GUIDES_DOCS_DIR:-apps/wiki/docs/guides}"
  local scripts_target="${SCRIPTS_DOCS_DIR:-apps/wiki/docs/scripts}"
  
  # Create target directories
  mkdir -p "$apps_target" "$infra_target" "$guides_target" "$scripts_target"

  # Collect app documentation
  log_info "Collecting application documentation: $apps_source/ → $apps_target/"
  for app_dir in "${PROJECT_ROOT}/${apps_source}/"*/ ; do
    [ -d "$app_dir" ] || continue
    local app_name="$(basename "$app_dir")"
    
    # Skip the wiki app to avoid copying into itself
    [ "$app_name" = "wiki" ] && continue
    
    local readme_file="${app_dir%/}/README.md"
    [ -f "$readme_file" ] || continue
    
    local target_dir="${PROJECT_ROOT}/${apps_target}/${app_name}"
    mkdir -p "$target_dir"
    
    # Copy README as index.md
    iconv -f UTF-8 -t UTF-8 -c "$readme_file" > "${target_dir}/index.md" 2>/dev/null || cp "$readme_file" "${target_dir}/index.md"
    
    # Copy asset directories if they exist
    for asset_dir in images img assets docs media static; do
      if [ -d "${app_dir%/}/${asset_dir}" ]; then
        rm -rf "${target_dir}/${asset_dir}"
        cp -R "${app_dir%/}/${asset_dir}" "${target_dir}/"
      fi
    done
  done

  # Collect infrastructure documentation
  log_info "Collecting infrastructure documentation: $infra_source/ → $infra_target/"
  for infra_dir in "${PROJECT_ROOT}/${infra_source}/"*/ ; do
    [ -d "$infra_dir" ] || continue
    local infra_name="$(basename "$infra_dir")"
    local readme_file="${infra_dir%/}/README.md"
    [ -f "$readme_file" ] || continue
    
    local target_dir="${PROJECT_ROOT}/${infra_target}/${infra_name}"
    mkdir -p "$target_dir"
    
    # Copy README as index.md
    iconv -f UTF-8 -t UTF-8 -c "$readme_file" > "${target_dir}/index.md" 2>/dev/null || cp "$readme_file" "${target_dir}/index.md"
    
    # Copy asset directories if they exist
    for asset_dir in images img assets docs media static; do
      if [ -d "${infra_dir%/}/${asset_dir}" ]; then
        rm -rf "${target_dir}/${asset_dir}"
        cp -R "${infra_dir%/}/${asset_dir}" "${target_dir}/"
      fi
    done
  done

  # Collect guides documentation
  log_info "Collecting guides documentation: $guides_source/ → $guides_target/"
  if [ -d "${PROJECT_ROOT}/${guides_source}" ]; then
    # Copy subdirectories with README files
    for guide_dir in "${PROJECT_ROOT}/${guides_source}/"*/ ; do
      [ -d "$guide_dir" ] || continue
      local guide_name="$(basename "$guide_dir")"
      local readme_file="${guide_dir%/}/README.md"
      [ -f "$readme_file" ] || continue
      
      local target_dir="${PROJECT_ROOT}/${guides_target}/${guide_name}"
      mkdir -p "$target_dir"
      
      # Copy README as index.md
      iconv -f UTF-8 -t UTF-8 -c "$readme_file" > "${target_dir}/index.md" 2>/dev/null || cp "$readme_file" "${target_dir}/index.md"
      
      # Copy asset directories if they exist
      for asset_dir in images img assets docs media static; do
        if [ -d "${guide_dir%/}/${asset_dir}" ]; then
          rm -rf "${target_dir}/${asset_dir}"
          cp -R "${guide_dir%/}/${asset_dir}" "${target_dir}/"
        fi
      done
    done
    
    # Copy standalone markdown files as individual guide directories
    for markdown_file in "${PROJECT_ROOT}/${guides_source}/"*.md ; do
      [ -f "$markdown_file" ] || continue
      local guide_name="$(basename "$markdown_file" .md)"
      local target_dir="${PROJECT_ROOT}/${guides_target}/${guide_name}"
      mkdir -p "$target_dir"
      
      # Copy markdown file as index.md
      iconv -f UTF-8 -t UTF-8 -c "$markdown_file" > "${target_dir}/index.md" 2>/dev/null || cp "$markdown_file" "${target_dir}/index.md"
    done
  fi

  # Collect scripts documentation
  log_info "Collecting scripts documentation → $scripts_target/"
  local scripts_readme="${PROJECT_ROOT}/scripts/README.md"
  if [ -f "$scripts_readme" ]; then
    # Copy scripts README as main scripts documentation
    iconv -f UTF-8 -t UTF-8 -c "$scripts_readme" > "${PROJECT_ROOT}/${scripts_target}/index.md" 2>/dev/null || cp "$scripts_readme" "${PROJECT_ROOT}/${scripts_target}/index.md"
    
    # Create .pages file for proper MkDocs navigation
    cat > "${PROJECT_ROOT}/${scripts_target}/.pages" <<EOF
nav:
  - index.md
EOF
  fi

  # Create landing page if it doesn't exist
  local landing_page="${PROJECT_ROOT}/${DOCS_DIR:-apps/wiki/docs}/index.md"
  if [ ! -f "$landing_page" ]; then
    cat > "$landing_page" <<'EOF'
# Documentation

Welcome to the documentation hub. Navigate using the sidebar to explore different sections.
EOF
  fi

  # Fix relative links to point to directories instead of .md files
  find "${PROJECT_ROOT}/apps/wiki/docs" -name "*.md" -exec sed -i -E 's|\]\(([A-Za-z0-9_-]+)\.md\)|](\1/)|g' {} +
}

# Build the documentation site
build_site() {
  local site_dir="${PROJECT_ROOT}/apps/wiki/site"
  
  # Clean site directory for fresh build
  if [ -d "$site_dir" ]; then
    log_info "Cleaning site directory for fresh build"
    rm -rf "$site_dir"
  fi
  mkdir -p "$site_dir"

  # Collect all documentation
  collect_documentation

  # Ensure required directories exist
  mkdir -p "${PROJECT_ROOT}/apps/wiki/docs/assets" "${PROJECT_ROOT}/apps/wiki/docs/templates"
  
  # Copy overrides directory if it exists
  if [ -d "${PROJECT_ROOT}/apps/wiki/docs/overrides" ]; then
    mkdir -p "${PROJECT_ROOT}/apps/wiki/docs/overrides"
  fi

  # Build the site
  mkdocs build --config-file "${PROJECT_ROOT}/apps/wiki/mkdocs.yml" --site-dir "$site_dir"
  
  log_success "Built wiki site for current branch"
}

# Main script execution
main() {
  local command="${1:-help}"
  
  case "$command" in
    build|sync)
      build_site
      ;;
    config)
      generate_mkdocs_config
      ;;
    collect)
      collect_documentation
      ;;
    help|--help|-h)
      cat <<EOF
Usage: $SCRIPT_NAME <command>

Commands:
  build, sync    Build the complete wiki documentation site
  config         Generate only the MkDocs configuration file
  collect        Collect documentation without building
  help           Show this help message

Examples:
  $SCRIPT_NAME build       # Build complete wiki site
  $SCRIPT_NAME sync        # Same as build (for compatibility)
  $SCRIPT_NAME config      # Generate mkdocs.yml only
EOF
      ;;
    *)
      echo "Error: Unknown command '$command'"
      echo "Run '$SCRIPT_NAME help' for usage information"
      exit 1
      ;;
  esac
}

# Set script name for help display
SCRIPT_NAME="$(basename "$0")"

# Run main function with all arguments
main "$@"