#!/bin/bash
set -eu

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

log_info "Installing pre-commit hooks..."

# === Pre-commit installation ===
if ! command -v pre-commit &> /dev/null; then
  log_info "Installing pre-commit..."
  pip install pre-commit
fi

# Install pre-commit hooks
pre-commit install

log_success "Pre-commit hooks installed successfully."