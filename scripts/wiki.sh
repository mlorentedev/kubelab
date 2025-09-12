#!/bin/zsh
# Collect Markdown from the mono-repo into apps/wiki/docs/_imported
set -euo pipefail
setopt nullglob

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_ROOT="${PROJECT_ROOT}/.env"
ENV_APP="${PROJECT_ROOT}/apps/wiki/.env"

source "$SCRIPT_DIR/utils.sh"
load_env_file "$ENV_ROOT" || true
load_env_file "$ENV_APP" || true

features_to_yaml() {
  local s="${MATERIAL_FEATURES:-}"
  if [ -z "$s" ]; then
    printf "    - navigation.instant\n    - navigation.tracking\n    - content.code.copy\n"
    return
  fi
  IFS=',' read -r -A arr <<< "$s"
  for item in "${arr[@]}"; do
    item="$(printf '%s' "$item" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [ -n "$item" ] && printf "    - %s\n" "$item"
  done
}

render_mkdocs_cfg() {
  local tmpl="${PROJECT_ROOT}/apps/wiki/mkdocs.yml.tmpl"
  local out="${PROJECT_ROOT}/apps/wiki/mkdocs.yml"
  local tmp="${out}.tmp"
  [ -f "$tmpl" ] || exit_error "Template not found: $tmpl"

  export MATERIAL_FEATURES_YAML="$(features_to_yaml)"
  envsubst < "$tmpl" > "$tmp"
  mv "$tmp" "$out"
  log_success "Generated mkdocs.yml"
}

collect_readmes() {
  local apps_dir="${APPS_DIR:-apps}"
  local dst_dir="${APPS_DOCS_DIR:-apps/wiki/docs/apps}"
  local infra_dir="${INFRA_DIR:-infra}"
  local infra_dst_dir="${INFRA_DOCS_DIR:-apps/wiki/docs/infra}"
  local guides_dir="${GUIDES_DIR:-docs}"
  local guides_dst_dir="${GUIDES_DOCS_DIR:-apps/wiki/docs/guides}"
  local scripts_dst_dir="${SCRIPTS_DOCS_DIR:-apps/wiki/docs/scripts}"
  
  mkdir -p "$dst_dir" "$infra_dst_dir" "$guides_dst_dir" "$scripts_dst_dir"

  log_info "Collecting READMEs from ${apps_dir}/ → ${dst_dir}/"
  for d in "${PROJECT_ROOT}/${apps_dir}/"*/ ; do
    [ -d "$d" ] || continue
    local app="$(basename "$d")"
    local src="${d%/}/README.md"
    [ -f "$src" ] || continue
    local dd="${PROJECT_ROOT}/${dst_dir}/${app}"
    mkdir -p "$dd"
    iconv -f UTF-8 -t UTF-8 -c "$src" > "${dd}/index.md" 2>/dev/null || cp "$src" "${dd}/index.md"
    for af in ${ASSET_DIRS:-images img assets docs media static}; do
      if [ -d "${d%/}/${af}" ]; then
        rm -rf "${dd}/${af}"
        cp -R "${d%/}/${af}" "${dd}/"
      fi
    done
  done

  log_info "Collecting READMEs from ${infra_dir}/ → ${infra_dst_dir}/"
  for d in "${PROJECT_ROOT}/${infra_dir}/"*/ ; do
    [ -d "$d" ] || continue
    local infra_app="$(basename "$d")"
    local src="${d%/}/README.md"
    [ -f "$src" ] || continue
    local dd="${PROJECT_ROOT}/${infra_dst_dir}/${infra_app}"
    mkdir -p "$dd"
    iconv -f UTF-8 -t UTF-8 -c "$src" > "${dd}/index.md" 2>/dev/null || cp "$src" "${dd}/index.md"
    for af in ${ASSET_DIRS:-images img assets docs media static}; do
      if [ -d "${d%/}/${af}" ]; then
        rm -rf "${dd}/${af}"
        cp -R "${d%/}/${af}" "${dd}/"
      fi
    done
  done

  log_info "Collecting READMEs from ${guides_dir}/ → ${guides_dst_dir}/"
  if [ -d "${PROJECT_ROOT}/${guides_dir}" ]; then
    local found_subdirs=false
    for d in "${PROJECT_ROOT}/${guides_dir}/"*/ ; do
      [ -d "$d" ] || continue
      found_subdirs=true
      local guides_app="$(basename "$d")"
      local src="${d%/}/README.md"
      [ -f "$src" ] || continue
      local dd="${PROJECT_ROOT}/${guides_dst_dir}/${guides_app}"
      mkdir -p "$dd"
      iconv -f UTF-8 -t UTF-8 -c "$src" > "${dd}/index.md" 2>/dev/null || cp "$src" "${dd}/index.md"
      for af in ${ASSET_DIRS:-images img assets docs media static}; do
        if [ -d "${d%/}/${af}" ]; then
          rm -rf "${dd}/${af}"
          cp -R "${d%/}/${af}" "${dd}/"
        fi
      done
    done
    
    # If no subdirectories found, try direct .md files and create subdirectories for each
    for f in "${PROJECT_ROOT}/${guides_dir}/"*.md ; do
      [ -f "$f" ] || continue
      local filename="$(basename "$f" .md)"
      local dd="${PROJECT_ROOT}/${guides_dst_dir}/${filename}"
      mkdir -p "$dd"
      iconv -f UTF-8 -t UTF-8 -c "$f" > "${dd}/index.md" 2>/dev/null || cp "$f" "${dd}/index.md"
    done
  fi

  # Collect scripts documentation from the actual scripts README
  log_info "Collecting scripts documentation → ${scripts_dst_dir}/"
  local scripts_src="${PROJECT_ROOT}/scripts/README.md"
  if [ -f "$scripts_src" ]; then
    # Use the actual scripts README as the main scripts documentation
    iconv -f UTF-8 -t UTF-8 -c "$scripts_src" > "${PROJECT_ROOT}/${scripts_dst_dir}/index.md" 2>/dev/null || cp "$scripts_src" "${PROJECT_ROOT}/${scripts_dst_dir}/index.md"
    # Create .pages file for scripts to ensure MkDocs processes it correctly
    cat > "${PROJECT_ROOT}/${scripts_dst_dir}/.pages" <<EOF
nav:
  - index.md
EOF
  fi

  local landing="${PROJECT_ROOT}/${DOCS_DIR:-apps/wiki/docs}/index.md"
  if [ ! -f "$landing" ]; then
    cat > "$landing" <<'EOF'
# Apps Documentation

Select an app from the sidebar.
EOF
  fi

  # Fix links to other markdown files to point to directories instead
  find "${PROJECT_ROOT}/apps/wiki/docs" -name "*.md" -exec sed -i -E 's|\]\(([A-Za-z0-9_-]+)\.md\)|](\1/)|g' {} +
}

branch_slug() {
  echo "${1//\//-}"
}

list_remote_branches() {
  local pat="$1"
  if [[ "$pat" == *"*"* || "$pat" == *"?"* || "$pat" == *"["* ]]; then
    git ls-remote --heads origin "$pat" | awk -F'refs/heads/' '{print $2}'
  else
    if git ls-remote --heads origin "$pat" >/dev/null 2>&1; then
      echo "$pat"
    fi
  fi
}

remote_branch_commit() {
  local branch="$1"
  git ls-remote --heads origin "$branch" | awk '{print $1}' | head -n1
}

build_one_branch_site() {
  local branch="$1"
  local slug; slug="$(branch_slug "$branch")"
  local site_base="${PROJECT_ROOT}/apps/wiki/site"
  local tmpdir; tmpdir="$(mktemp -d -t "wiki-${slug}-XXXXXXXX")" || exit 1

  local commit; commit="$(remote_branch_commit "$branch")"
  if [ -z "$commit" ]; then
    echo "[WARN] Remote branch not found: origin/${branch}. Skipping."
    rm -rf "${tmpdir}"
    return 0
  fi

  local ORIG_ROOT="${PROJECT_ROOT}"

  git -C "${PROJECT_ROOT}" archive --format=tar "${commit}" | tar -C "${tmpdir}" -xf -

  cp -f "${PROJECT_ROOT}/.env" "${tmpdir}/.env" 2>/dev/null || true
  mkdir -p "${tmpdir}/apps/wiki"
  cp -f "${PROJECT_ROOT}/apps/wiki/.env" "${tmpdir}/apps/wiki/.env" 2>/dev/null || true

  (
    cd "${tmpdir}" || exit 1

    PROJECT_ROOT="$PWD"
    SCRIPT_DIR="$PROJECT_ROOT/tools"
    ENV_ROOT="$PROJECT_ROOT/.env"
    ENV_APP="$PROJECT_ROOT/apps/wiki/.env"
    [ -f "$SCRIPT_DIR/utils.sh" ] && { source "$SCRIPT_DIR/utils.sh"; load_env_file "$ENV_ROOT" || true; load_env_file "$ENV_APP" || true; }

    : "${APPS_DIR:=apps}"
    : "${APPS_DOCS_DIR:=apps/wiki/docs/apps}"
    : "${INFRA_DIR:=infra}"
    : "${INFRA_DOCS_DIR:=apps/wiki/docs/infra}"
    : "${SCRIPTS_DOCS_DIR:=apps/wiki/docs/scripts}"
    : "${DOCS_DIR:=apps/wiki/docs}"

    collect_readmes

    # Debug: Check what's in the scripts docs directory
    echo "DEBUG: Contents of scripts docs directory:"
    ls -la "${DOCS_DIR}/scripts/" || echo "Scripts directory not found"
    if [ -f "${DOCS_DIR}/scripts/index.md" ]; then
      echo "DEBUG: Scripts index.md exists with $(wc -l < "${DOCS_DIR}/scripts/index.md") lines"
    fi
    if [ -f "${DOCS_DIR}/scripts/.pages" ]; then
      echo "DEBUG: Scripts .pages exists"
      cat "${DOCS_DIR}/scripts/.pages"
    fi

    mkdir -p "${DOCS_DIR}/assets" "${DOCS_DIR}/templates"
    # Copy all assets from the original location
    if [ -d "${ORIG_ROOT}/${DOCS_DIR}/assets" ]; then
      cp -rf "${ORIG_ROOT}/${DOCS_DIR}/assets/"* "${DOCS_DIR}/assets/" || true
    fi
    
    # Copy templates directory if it exists
    if [ -d "${ORIG_ROOT}/${DOCS_DIR}/templates" ]; then
      cp -r "${ORIG_ROOT}/${DOCS_DIR}/templates/"* "${DOCS_DIR}/templates/" || true
    fi
    
    # Copy overrides directory if it exists
    if [ -d "${ORIG_ROOT}/${DOCS_DIR}/overrides" ]; then
      cp -r "${ORIG_ROOT}/${DOCS_DIR}/overrides" "${DOCS_DIR}/" || true
    fi

    printf "window.__BRANCHES__ = %s;\nwindow.__CURRENT_BRANCH__ = '%s';\n" \
      "${ALL_BRANCH_SLUGS_JS:-'[]'}" "${slug}" \
      > "${DOCS_DIR}/assets/branch-data.js"

    export DOCS_DIR_REL="docs"

    [ -f "apps/wiki/mkdocs.yml.tmpl" ] || { mkdir -p "apps/wiki"; cp -f "${ORIG_ROOT}/apps/wiki/mkdocs.yml.tmpl" "apps/wiki/mkdocs.yml.tmpl"; }
    render_mkdocs_cfg

    local out_dir="${site_base}/${slug}"
    mkdir -p "${out_dir}"
    mkdocs build --config-file "apps/wiki/mkdocs.yml" --site-dir "${out_dir}"
  )

  rm -rf "${tmpdir}"
  log_success "Built site for branch '${branch}' → ${site_base}/${slug}"
}

build_all_branches_site() {
  local specs=(${=WIKI_BRANCHES:-"develop master"})
  local branches=()
  
  # Clean site directory to ensure fresh builds
  local site_base="${PROJECT_ROOT}/apps/wiki/site"
  if [ -d "$site_base" ]; then
    log_info "Cleaning site directory for fresh build"
    rm -rf "$site_base"
  fi
  mkdir -p "$site_base"

  for spec in "${specs[@]}"; do
    while IFS= read -r b; do
      [ -n "$b" ] && branches+=("$b")
    done < <(list_remote_branches "$spec")
  done

  if [ "${#branches[@]}" -eq 0 ]; then
    log_info "No branches found matching patterns: ${specs[*]}"
    return 0
  fi

  local uniq=()
  typeset -A seen
  for b in "${branches[@]}"; do
    [[ -n "${seen[$b]:-}" ]] || { uniq+=("$b"); seen[$b]=1; }
  done

  local all_slugs_js="["; local first=1
  for b in "${uniq[@]}"; do
    local s; s="$(branch_slug "$b")"
    if [ $first -eq 0 ]; then all_slugs_js+=", "; fi
    all_slugs_js+="\"$s\""; first=0
  done
  all_slugs_js+="]"
  export ALL_BRANCH_SLUGS_JS="$all_slugs_js"

  for b in "${uniq[@]}"; do
    build_one_branch_site "${b}"
    create_section_indexes "${b}"
  done
}

slugify_branch() {
  s="$(printf '%s' "$1" | awk '{print tolower($0)}')"
  printf '%s\n' "$s" | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
}

title_case() {
  printf '%s' "$1" \
  | sed 's/[-_]/ /g' \
  | awk '{for(i=1;i<=NF;i++){ $i=toupper(substr($i,1,1)) substr($i,2)} }1'
}

get_section_description() {
  local section="$1"
  case "$section" in
    apps)
      echo "Discover all applications in the mlorente.dev ecosystem. Here you'll find everything from robust APIs developed in Go to modern React user interfaces, dynamic Jekyll blogs, and advanced automation tools. Each application is designed with the highest quality standards and thoroughly documented for easy understanding and maintenance."
      ;;
    infra)
      echo "Explore the infrastructure that supports the mlorente.dev ecosystem. This section includes reverse proxy configurations with Traefik, optimized web servers with Nginx, and deployment automation tools with Ansible. Everything is containerized with Docker and orchestrated to ensure high availability, scalability, and easy maintenance in production environments."
      ;;
    scripts)
      echo "Learn about all automation scripts and project utilities. Includes tools for environment configuration, automatic configuration generation, CI/CD scripts, and development utilities. All scripts are documented with usage examples and follow shell scripting best practices to ensure reliability and maintainability."
      ;;
    guides)
      echo "Access comprehensive technical documentation covering everything from quick start guides to advanced architectural documentation. Includes technical decision records, contribution guides, CI/CD procedures, deployment strategies, and troubleshooting. All documentation is written with a practical and conversational approach for easy understanding."
      ;;
  esac
}

get_app_description() {
  local app="$1"
  case "$app" in
    api)
      echo "REST API developed in Go with clean architecture, providing secure and efficient endpoints for the ecosystem. Includes JWT authentication, robust validation, and automatic Swagger documentation."
      ;;
    blog)
      echo "Personal blog developed in Jekyll with responsive design and SEO optimization. Includes comment system, automatic categorization, and integration with analytics tools."
      ;;
    web)
      echo "Main website developed in React with TypeScript, showcasing the professional portfolio. Includes smooth animations, adaptive design, and integration with content management systems."
      ;;
    monitoring)
      echo "Complete monitoring stack with Prometheus, Grafana, and Alertmanager. Provides real-time metrics, customizable dashboards, and automatic alerts to ensure system health."
      ;;
    n8n)
      echo "Workflow automation tool that allows creating automated processes without code. Integrates multiple services and APIs to optimize repetitive tasks and improve productivity."
      ;;
    portainer)
      echo "Intuitive web interface for Docker container management. Facilitates visual administration of containers, volumes, networks, and complete stacks without command line needs."
      ;;
    wiki)
      echo "Technical documentation system developed with MkDocs and Material Theme. Provides versioned documentation, advanced search, and intuitive navigation for the entire ecosystem."
      ;;
  esac
}

get_infra_description() {
  local infra="$1"
  case "$infra" in
    traefik)
      echo "Modern automatic reverse proxy that manages traffic routing, automatic SSL certificates with Let's Encrypt, and load balancing. Configured for Docker service auto-discovery."
      ;;
    nginx)
      echo "High-performance web server configured as reverse proxy and static content server. Includes cache optimizations, gzip compression, and advanced security configurations."
      ;;
    ansible)
      echo "Infrastructure automation tool that manages deployments, server configurations, and maintenance tasks. Includes playbooks for different environments and reusable roles."
      ;;
  esac
}

get_script_description() {
  local script="$1"
  case "$script" in
    index)
      echo "Complete documentation of all project automation scripts. Includes tools for environment configuration, configuration generation, CI/CD scripts, and development utilities with detailed usage examples."
      ;;
    *)
      echo "Automation scripts and tools for project development, configuration, and maintenance. Includes utilities for environment management and configuration generation."
      ;;
  esac
}

get_guide_description() {
  local guide="$1"
  case "$guide" in
    "ARCHITECTURE-AND-DECISIONS"|"ADR"|"ARCHITECTURE")
      echo "Architectural decision records documenting important technical decisions of the project. Explains the context, options considered, and reasons behind each technological decision."
      ;;
    "CI-CD")
      echo "Complete CI/CD pipeline documentation with GitHub Actions. Includes automated workflows, testing strategies, automatic deployment, and semantic version management."
      ;;
    "CONTRIBUTING")
      echo "Complete guide for contributors explaining the workflow, code conventions, pull request process, and best practices to maintain project quality."
      ;;
    "DEPLOYMENT")
      echo "Advanced deployment guide covering server configuration, deployment procedures, emergency rollbacks, and specific configurations for different environments."
      ;;
    "HOW-TO")
      echo "Quick reference guide with commands, step-by-step procedures, and solutions to common problems. Ideal for quick queries during development and maintenance."
      ;;
    "TROUBLESHOOTING")
      echo "Troubleshooting guide covering the most common errors, their causes, and step-by-step solutions. Includes container debugging, network issues, and configuration errors."
      ;;
    "VERSIONING")
      echo "Automatic semantic versioning strategy explaining how versions are calculated, release tagging, and Docker image management in different environments."
      ;;
    "WIKI")
      echo "Documentation about the wiki system itself, including its architecture, generation system, configuration, and how to contribute to the project's technical documentation."
      ;;
    "CUBELAB")
      echo "Documentation about the CubeLab laboratory environment, including its configuration, available tools, and how to use it for experimentation and development."
      ;;
    "SCRIPTS")
      echo "Complete documentation of all project scripts and tools. Includes configuration generators, automation scripts, development utilities, and CI/CD tools."
      ;;
  esac
}

generate_section_index() {
  local slug="$1"         # e.g. hotfix-ci-cd-pipeline-fix
  local section="$2"      # e.g. apps | infra | guides
  local title="$3"        # e.g. Apps | Infra | Guides
  local site_dir="${SITE_DIR:-${PROJECT_ROOT}/apps/wiki/site}"  
  local base="${site_dir}/${slug}/${section}"

  # Create the directory if it doesn't exist (fixes missing infra issue)
  mkdir -p "${base}"

  local template_path="${PROJECT_ROOT}/apps/wiki/docs/templates/section-index.html"
  
  # Check if template exists
  if [ ! -f "$template_path" ]; then
    echo "⚠️  Template not found: $template_path"
    return 1
  fi

  # Determine section number for sequential numbering
  local section_number=""
  case "$section" in
    apps)    section_number="1" ;;
    infra)   section_number="2" ;;
    scripts) section_number="3" ;;
    guides)  section_number="4" ;;
  esac

  # Collect items with rich descriptions and sequential numbering
  local items=""
  local counter=1
  
  # Use a simpler approach to get subdirectories
  for d in "$base"/*/ ; do
    [ -d "$d" ] || continue
    local name=$(basename "$d")
    if [ -f "$d/index.html" ]; then
      local pretty=$(title_case "$name")
      local description=""
      local item_number="${section_number}.${counter}"
      
      # Get appropriate description based on section
      case "$section" in
        apps)    description=$(get_app_description "$name") ;;
        infra)   description=$(get_infra_description "$name") ;;
        scripts) description=$(get_script_description "$name") ;;
        guides)  description=$(get_guide_description "$name") ;;
      esac
      
      items="${items}<div class=\"section-card\">
        <h3><a href=\"./${name}/\"><span class=\"item-number\">${item_number}</span> ${pretty}</a></h3>
        <p>${description}</p>
        <div class=\"card-footer\">
          <div class=\"card-tags\">
            <span class=\"card-tag\">${section}</span>
          </div>
          <span>→</span>
        </div>
      </div>\n"
      
      counter=$((counter + 1))
    fi
  done

  # Determine section properties
  local section_icon="📚"
  local section_description=""
  local section_title_with_number="${section_number}. ${title}"
  
  case "$section" in
    apps)   
      section_icon="📱"
      section_description=$(get_section_description "apps")
      ;;
    infra)  
      section_icon="🔧"
      section_description=$(get_section_description "infra")
      ;;
    scripts)
      section_icon="⚙️"
      section_description=$(get_section_description "scripts")
      ;;
    guides) 
      section_icon="📖"
      section_description=$(get_section_description "guides")
      ;;
  esac

  # Prepare content - special handling for scripts section
  local content
  if [ -n "$items" ]; then
    content="<div class=\"section-cards\">\n${items}</div>"
  else
    # Check if this is the scripts section with actual content
    if [ "$section" = "scripts" ]; then
      # For scripts, check if MkDocs built a scripts/index.html from the README content
      local mkdocs_scripts_file="${SITE_DIR}/${slug}/scripts/index.html"
      if [ -f "$mkdocs_scripts_file" ]; then
        echo "⚙️  Scripts section has README content, using MkDocs-generated page instead of empty section index"
        return 0
      else
        # Fallback to regular empty message if MkDocs didn't build the scripts page
        content="<div class=\"no-content-message\">
          <div class=\"icon\">📭</div>
          <h3>No content available</h3>
          <p>This section will be available soon with documentation and additional resources.</p>
        </div>"
      fi
    else
      content="<div class=\"no-content-message\">
        <div class=\"icon\">📭</div>
        <h3>No content available</h3>
        <p>This section will be available soon with documentation and additional resources.</p>
      </div>"
    fi
  fi

  # Set active tab classes
  local apps_active=""
  local infra_active=""
  local scripts_active=""
  local guides_active=""
  
  case "$section" in
    apps)    apps_active="active-nav" ;;
    infra)   infra_active="active-nav" ;;
    scripts) scripts_active="active-nav" ;;
    guides)  guides_active="active-nav" ;;
  esac

  # Generate HTML from template using a manual replacement approach
  local temp_html="${base}/index.tmp.html"
  local final_html="${base}/index.html"
  
  # Read template and perform replacements line by line
  while IFS= read -r line; do
    # Replace simple placeholders first
    line="${line//\{\{SECTION_TITLE\}\}/$section_title_with_number}"
    line="${line//\{\{BRANCH_SLUG\}\}/$slug}"
    line="${line//\{\{SECTION_PATH\}\}/$section}"
    line="${line//\{\{SECTION_ICON\}\}/$section_icon}"
    line="${line//\{\{APPS_ACTIVE\}\}/$apps_active}"
    line="${line//\{\{INFRA_ACTIVE\}\}/$infra_active}"
    line="${line//\{\{SCRIPTS_ACTIVE\}\}/$scripts_active}"
    line="${line//\{\{GUIDES_ACTIVE\}\}/$guides_active}"
    
    # Handle complex replacements
    if [[ "$line" == *"{{SECTION_DESCRIPTION}}"* ]]; then
      line="${line//\{\{SECTION_DESCRIPTION\}\}/$section_description}"
    fi
    if [[ "$line" == *"{{CONTENT_PLACEHOLDER}}"* ]]; then
      line="${line//\{\{CONTENT_PLACEHOLDER\}\}/$content}"
    fi
    
    echo "$line"
  done < "$template_path" > "$final_html"

  echo "✅ generated: ${base}/index.html"
}

# Generate section indexes for a branch (slug)
create_section_indexes() {
  local branch="${1:-$(git rev-parse --abbrev-ref HEAD)}"
  local slug
  if type branch_slug >/dev/null 2>&1; then
    slug="$(branch_slug "${branch}")"
  else
    slug="$(slugify_branch "${branch}")"
  fi

  # Always generate indexes for all sections, even if empty
  local sections=(apps infra scripts guides)
  for s in "${sections[@]}"; do
    case "$s" in
      apps)    generate_section_index "${slug}" "apps"    "Apps" ;;
      infra)   generate_section_index "${slug}" "infra"   "Infra" ;;
      scripts) 
        # Scripts section has a single README file that MkDocs processes directly
        # Don't generate a section index template as it would override the MkDocs-rendered content
        echo "ℹ️  Skipping section index generation for scripts (MkDocs renders README content directly)"
        ;;
      guides)  generate_section_index "${slug}" "guides"  "Guides" ;;
    esac
  done
}

cmd="${1:-help}"
case "$cmd" in
  sync)
    build_all_branches_site
    ;;
  build-one)
    build_one_branch_site "${2:-$(git rev-parse --abbrev-ref HEAD)}"
    create_section_indexes "${2:-$(git rev-parse --abbrev-ref HEAD)}"
    ;;
  *)
    echo "Usage: $0 {sync|build-one <branch>}"
    ;;
esac
