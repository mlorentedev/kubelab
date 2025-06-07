#!/bin/bash
# create-env-example.sh - Create a .env.example file with placeholder values
# Usage: ./create-env-example.sh [INPUT_FILE]

set -e

# Get script and project root directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source utility functions if available (e.g., log_error, log_info)
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

# Determine input file (default to ".env" or first argument)
INPUT_FILE="${1:-.env}"

# Verify input file exists; otherwise fallback to "./.env"
if [ ! -f "$INPUT_FILE" ]; then
    if [ -f ".env" ]; then
        INPUT_FILE=".env"
    else
        log_error "Input file not found: $INPUT_FILE"
        exit 1
    fi
fi

# Derive output filename: same directory and name with ".example" suffix
INPUT_DIR="$(dirname "$INPUT_FILE")"
INPUT_BASE="$(basename "$INPUT_FILE")"
OUTPUT_FILE="$INPUT_DIR/${INPUT_BASE}.example"

log_info "Generating placeholder file from: $INPUT_FILE"
touch "$OUTPUT_FILE"
log_info "Output will be: $OUTPUT_FILE"

# Build the placeholder file
{
    echo "# Environment variables placeholder file"
    echo "# Copy this file to .env and replace PLACEHOLDER values with actual values"
    echo "# Generated from: $INPUT_FILE"
    echo "# Generated on: $(date)"
    echo ""
    
    while IFS= read -r line || [ -n "$line" ]; do
        # Preserve comments and blank lines
        if [[ "$line" =~ ^#.*$ || -z "$line" ]]; then
            echo "$line"
            continue
        fi
        
        # If line doesn't contain '=', output it unchanged
        if [[ ! "$line" =~ = ]]; then
            echo "$line"
            continue
        fi
        
        # Extract key and replace value with "PLACEHOLDER"
        key="${line%%=*}"
        echo "${key}=PLACEHOLDER"
    done < "$INPUT_FILE"
} > "$OUTPUT_FILE"

log_success "Placeholder file created: $OUTPUT_FILE"
log_info "Next steps:"
log_info "1. Copy $OUTPUT_FILE to .env"
log_info "2. Replace PLACEHOLDER values with actual values"
log_info "3. Do not commit the .env file with real values"
