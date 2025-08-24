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
  local general_dir="${GENERAL_DIR:-docs}"
  local general_dst_dir="${GENERAL_DOCS_DIR:-apps/wiki/docs/guides}"
  
  mkdir -p "$dst_dir" "$infra_dst_dir" "$general_dst_dir"

  log_info "Collecting READMEs from ${apps_dir}/ → ${dst_dir}/"
  for d in "${PROJECT_ROOT}/${apps_dir}/"*/ ; do
    [ -d "$d" ] || continue
    local app="$(basename "$d")"
    [ "$app" = "wiki" ] && continue
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

  log_info "Collecting READMEs from ${general_dir}/ → ${general_dst_dir}/"
  
  # Check if general_dir exists
  if [ -d "${PROJECT_ROOT}/${general_dir}" ]; then
    # First try subdirectories with README.md files
    local found_subdirs=false
    for d in "${PROJECT_ROOT}/${general_dir}/"*/ ; do
      [ -d "$d" ] || continue
      found_subdirs=true
      local general_app="$(basename "$d")"
      local src="${d%/}/README.md"
      [ -f "$src" ] || continue
      local dd="${PROJECT_ROOT}/${general_dst_dir}/${general_app}"
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
      for f in "${PROJECT_ROOT}/${general_dir}/"*.md ; do
        [ -f "$f" ] || continue
        local filename="$(basename "$f" .md)"
        local dd="${PROJECT_ROOT}/${general_dst_dir}/${filename}"
        mkdir -p "$dd"
        iconv -f UTF-8 -t UTF-8 -c "$f" > "${dd}/index.md" 2>/dev/null || cp "$f" "${dd}/index.md"
      done
    fi
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
    : "${DOCS_DIR:=apps/wiki/docs}"

    collect_readmes

    mkdir -p "${DOCS_DIR}/assets"
    # Copy all assets from the original location
    if [ -d "${ORIG_ROOT}/${DOCS_DIR}/assets" ]; then
      cp -rf "${ORIG_ROOT}/${DOCS_DIR}/assets/"* "${DOCS_DIR}/assets/" || true
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
  done
}

cmd="${1:-help}"
case "$cmd" in
  sync)
    build_all_branches_site
    ;;
  build-one)
    build_one_branch_site "${2:-$(git rev-parse --abbrev-ref HEAD)}"
    ;;
  *)
    echo "Usage: $0 {sync|build-one <branch>}"
    ;;
esac
