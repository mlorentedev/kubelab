#!/bin/bash
# generate-env-example.sh - Create a .env.example file with placeholder values
# Usage: ./generate-env-example.sh .env.dev

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/utils.sh" ] && source "$SCRIPT_DIR/utils.sh"

INPUT_FILE="$1"

if [ -z "$INPUT_FILE" ]; then
    log_error "No input file provided. Usage: $0 .env.dev"
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    log_error "Input file not found: $INPUT_FILE"
    exit 1
fi

# Derive ENVIRONMENT from the suffix of the file (after .env.)
ENVIRONMENT="${INPUT_FILE##*.env.}"

# Derive output filename
OUTPUT_FILE="${INPUT_FILE}.example"

log_info "Generating placeholder file from: $INPUT_FILE"
log_info "Environment detected: $ENVIRONMENT"
log_info "Output will be: $OUTPUT_FILE"

{
    echo "# Environment variables placeholder file"
    echo "# Copy this file to .env.${ENVIRONMENT} and replace PLACEHOLDER values with actual values"
    echo "# Generated from: $INPUT_FILE"
    echo "# Generated on: $(date)"
    echo ""

    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^#.*$ || -z "$line" ]]; then
            echo "$line"
            continue
        fi
        if [[ ! "$line" =~ = ]]; then
            echo "$line"
            continue
        fi
        key="${line%%=*}"
        echo "${key}=PLACEHOLDER"
    done < "$INPUT_FILE"
} > "$OUTPUT_FILE"

log_success "Placeholder file created: $OUTPUT_FILE"
log_info "Please remember to replace PLACEHOLDER values with actual values."