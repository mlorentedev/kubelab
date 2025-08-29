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
    if [ "$found_subdirs" = false ]; then
      for f in "${PROJECT_ROOT}/${guides_dir}/"*.md ; do
        [ -f "$f" ] || continue
        local filename="$(basename "$f" .md)"
        local dd="${PROJECT_ROOT}/${guides_dst_dir}/${filename}"
        mkdir -p "$dd"
        iconv -f UTF-8 -t UTF-8 -c "$f" > "${dd}/index.md" 2>/dev/null || cp "$f" "${dd}/index.md"
      done
    fi
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
# Documentación de las apps

Selecciona una app en la barra lateral.
EOF
  fi
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
    echo "[WARN] Rama remota no encontrada: origin/${branch}. Me la salto."
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
      echo "Descubre todas las aplicaciones del ecosistema mlorente.dev. Aquí encontrarás desde APIs robustas desarrolladas en Go hasta interfaces de usuario modernas en React, pasando por blogs dinámicos en Jekyll y herramientas de automatización avanzadas. Cada aplicación está diseñada con los más altos estándares de calidad y documentada en detalle para facilitar su comprensión y mantenimiento."
      ;;
    infra)
      echo "Explora la infraestructura que sustenta el ecosistema mlorente.dev. Esta sección incluye configuraciones de proxies reversos con Traefik, servidores web optimizados con Nginx, y herramientas de automatización de despliegues con Ansible. Todo está containerizado with Docker y orquestado para garantizar alta disponibilidad, escalabilidad y facilidad de mantenimiento en entornos de producción."
      ;;
    scripts)
      echo "Conoce todos los scripts de automatización y utilidades del proyecto. Incluye herramientas para configuración de entornos, generación automática de configuraciones, scripts de CI/CD, y utilidades de desarrollo. Todos los scripts están documentados con ejemplos de uso y siguen las mejores prácticas de shell scripting para garantizar su fiabilidad y mantenibilidad."
      ;;
    guides)
      echo "Accede a documentación técnica comprensiva que abarca desde guías de inicio rápido hasta documentación arquitectónica avanzada. Incluye registros de decisiones técnicas, guías de contribución, procedimientos de CI/CD, estrategias de deployment, y solución de problemas. Toda la documentación está escrita en español de España con un enfoque práctico y conversacional para facilitar su comprensión."
      ;;
  esac
}

get_app_description() {
  local app="$1"
  case "$app" in
    api)
      echo "API REST desarrollada en Go con arquitectura limpia, que proporciona endpoints seguros y eficientes para el ecosistema. Incluye autenticación JWT, validación robusta, y documentación Swagger automática."
      ;;
    blog)
      echo "Blog personal desarrollado en Jekyll con diseño responsive y optimizado para SEO. Incluye sistema de comentarios, categorización automática, y integración con herramientas de analytics."
      ;;
    web)
      echo "Sitio web principal desarrollado en React con TypeScript, que presenta el portafolio profesional. Incluye animaciones suaves, diseño adaptativo, y integración con sistemas de gestión de contenido."
      ;;
    monitoring)
      echo "Stack completo de monitorización con Prometheus, Grafana, y Alertmanager. Proporciona métricas en tiempo real, dashboards personalizables, y alertas automáticas para garantizar la salud del sistema."
      ;;
    n8n)
      echo "Herramienta de automatización de workflows que permite crear procesos automatizados sin código. Integra múltiples servicios y APIs para optimizar tareas repetitivas y mejorar la productividad."
      ;;
    portainer)
      echo "Interfaz web intuitiva para la gestión de contenedores Docker. Facilita la administración visual de contenedores, volúmenes, redes, y stacks completos sin necesidad de línea de comandos."
      ;;
    wiki)
      echo "Sistema de documentación técnica desarrollado con MkDocs y Material Theme. Proporciona documentación versionada, búsqueda avanzada, y navegación intuitiva para todo el ecosistema."
      ;;
  esac
}

get_infra_description() {
  local infra="$1"
  case "$infra" in
    traefik)
      echo "Proxy reverso moderno y automático que gestiona el enrutamiento de tráfico, certificados SSL automáticos con Let's Encrypt, y balanceador de carga. Configurado para auto-descubrimiento de servicios Docker."
      ;;
    nginx)
      echo "Servidor web de alto rendimiento configurado como proxy reverso y servidor de contenido estático. Incluye optimizaciones de cache, compresión gzip, y configuraciones de seguridad avanzadas."
      ;;
    ansible)
      echo "Herramienta de automatización de infraestructura que gestiona deployments, configuraciones de servidor, y tareas de mantenimiento. Incluye playbooks para diferentes entornos y roles reutilizables."
      ;;
  esac
}

get_script_description() {
  local script="$1"
  case "$script" in
    index)
      echo "Documentación completa de todos los scripts de automatización del proyecto. Incluye herramientas para configuración de entornos, generación de configuraciones, scripts de CI/CD, y utilidades de desarrollo con ejemplos de uso detallados."
      ;;
    *)
      echo "Scripts y herramientas de automatización para el desarrollo, configuración, y mantenimiento del proyecto. Incluye utilidades para gestión de entornos y generación de configuraciones."
      ;;
  esac
}

get_guide_description() {
  local guide="$1"
  case "$guide" in
    "ARCHITECTURE-AND-DECISIONS"|"ADR"|"ARCHITECTURE")
      echo "Registros de decisiones arquitectónicas que documentan las decisiones técnicas importantes del proyecto. Explica el contexto, las opciones consideradas, y las razones detrás de cada decisión tecnológica."
      ;;
    "CI-CD")
      echo "Documentación completa del pipeline de CI/CD con GitHub Actions. Incluye workflows automatizados, estrategias de testing, deployment automático, y gestión de versiones semánticas."
      ;;
    "CONTRIBUTING")
      echo "Guía completa para contribuidores que explica el flujo de trabajo, convenciones de código, proceso de pull requests, y mejores prácticas para mantener la calidad del proyecto."
      ;;
    "DEPLOYMENT")
      echo "Guía avanzada de despliegue que cubre configuración de servidores, procedimientos de deployment, rollbacks de emergencia, y configuraciones específicas para diferentes entornos."
      ;;
    "HOW-TO")
      echo "Guía de referencia rápida con comandos, procedimientos paso a paso, y soluciones a problemas comunes. Ideal para consultas rápidas durante el desarrollo y mantenimiento."
      ;;
    "TROUBLESHOOTING")
      echo "Guía de resolución de problemas que cubre los errores más comunes, sus causas, y soluciones paso a paso. Incluye debugging de containers, problemas de red, y errores de configuración."
      ;;
    "VERSIONING")
      echo "Estrategia de versionado semántico automático que explica cómo se calculan las versiones, el etiquetado de releases, y la gestión de imágenes Docker en diferentes entornos."
      ;;
    "WIKI")
      echo "Documentación sobre el propio sistema de wiki, incluyendo su arquitectura, sistema de generación, configuración, y cómo contribuir a la documentación técnica del proyecto."
      ;;
    "CUBELAB")
      echo "Documentación sobre el entorno de laboratorio CubeLab, incluyendo su configuración, herramientas disponibles, y cómo utilizarlo para experimentación y desarrollo."
      ;;
    "SCRIPTS")
      echo "Documentación completa de todos los scripts y herramientas del proyecto. Incluye generadores de configuración, scripts de automatización, utilidades de desarrollo, y herramientas para CI/CD."
      ;;
  esac
}

generate_section_index() {
  local slug="$1"         # e.g. hotfix-ci-cd-pipeline-fix
  local section="$2"      # e.g. apps | infra | guides
  local title="$3"        # e.g. Apps | Infra | Guides
  local base="${SITE_DIR}/${slug}/${section}"
  
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
          <h3>No hay contenido disponible</h3>
          <p>Esta sección estará disponible próximamente con documentación y recursos adicionales.</p>
        </div>"
      fi
    else
      content="<div class=\"no-content-message\">
        <div class=\"icon\">📭</div>
        <h3>No hay contenido disponible</h3>
        <p>Esta sección estará disponible próximamente con documentación y recursos adicionales.</p>
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
