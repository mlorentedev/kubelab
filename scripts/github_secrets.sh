#!/bin/bash

# GitHub Secrets Management Script

# Requirements:
# - GitHub CLI (gh) must be installed
# - Must be authenticated with gh
# - Requires .env file in parent direcyory

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Usage function
usage() {
    echo "Usage: $0 <repository> [options]"
    echo "Options:"
    echo "  -f, --file FILE    Specify custom .env file (default: .env)"
    echo "  -d, --dry-run     Show what would be done without making changes"
    echo "  -h, --help        Show this help message"
    exit 1
}

# Validate input
validate_secret() {
    local value="$1"
    
    # Check for empty or obviously placeholder values
    if [[ -z "$value" ]] || 
       [[ "$value" =~ ^(placeholder|change_me|your_value|secret)$ ]] || 
       [[ ${#value} -lt 4 ]]; then
        return 1
    fi
    return 0
}

# Main script
main() {
    local repo=""
    local env_file="..\.env"
    local dry_run=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--file)
                env_file="$2"
                shift 2
                ;;
            -d|--dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                if [[ -z "$repo" ]]; then
                    repo="$1"
                    shift
                else
                    echo "Invalid argument: $1"
                    usage
                fi
                ;;
        esac
    done

    # Validate repository
    if [[ -z "$repo" ]]; then
        echo "${RED}Error: Repository not specified${NC}"
        usage
    fi

    # Check if .env file exists
    if [[ ! -f "$env_file" ]]; then
        echo "${RED}Error: .env file not found at $env_file${NC}"
        exit 1
    fi

    # Check GitHub CLI
    if ! command -v gh &> /dev/null; then
        echo "${RED}Error: GitHub CLI (gh) is not installed${NC}"
        exit 1
    fi

    # Counters
    local created=0
    local skipped=0
    local invalid=0

    echo "${YELLOW}Processing secrets for $repo${NC}"
    if $dry_run; then
        echo "${YELLOW}[DRY RUN MODE]${NC}"
    fi

    # Read .env file and process secrets
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        # Skip comments and empty lines
        [[ "$key" =~ ^\s*#.* ]] && continue
        [[ -z "$key" ]] && continue

        # Trim whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)

        # Remove quotes if present
        value="${value%\"}"
        value="${value#\"}"

        # Validate secret
        if ! validate_secret "$value"; then
            echo "${RED}Skipping invalid secret: $key${NC}"
            ((invalid++))
            continue
        fi

        # Dry run or actual secret creation
        if $dry_run; then
            echo "${YELLOW}Would set secret: $key${NC}"
            ((created++))
        else
            if gh secret set "$key" -R "$repo" <<< "$value"; then
                echo "${GREEN}Set secret: $key${NC}"
                ((created++))
            else
                echo "${RED}Failed to set secret: $key${NC}"
                ((skipped++))
            fi
        fi
    done < "$env_file"

    # Print summary
    echo -e "\n${YELLOW}--- Secret Management Summary ---${NC}"
    echo -e "Repository: ${GREEN}$repo${NC}"
    echo -e "Env File: ${GREEN}$env_file${NC}"
    echo -e "Secrets Processed: ${GREEN}$((created + skipped + invalid))${NC}"
    echo -e "Created/Updated: ${GREEN}$created${NC}"
    echo -e "Skipped: ${YELLOW}$skipped${NC}"
    echo -e "Invalid: ${RED}$invalid${NC}"
}

# Run the main function
main "$@"