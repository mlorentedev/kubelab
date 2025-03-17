#!/bin/bash
# perf-test.sh - Run performance tests against the application
# Usage: ./perf-test.sh <environment> [path]
# Example: ./perf-test.sh staging /api/subscribe
set -e

# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

# Check dependencies
check_dependencies "curl" "ab"

# Check parameters
if [ "$#" -lt 1 ]; then
    exit_error "Missing environment.\nUsage: $0 <environment> [path]\nExample: $0 staging /api/subscribe"
fi

ENV=$1
PATH_TO_TEST=${2:-"/"}

# Validate environment
validate_environment "$ENV"

# Construct the full URL
FULL_URL="${SITE_URL}${PATH_TO_TEST}"

log_info "Running performance tests on $FULL_URL"

# Create report filename
REPORT_FILE="${ENV}_perf_test_$(date +%Y%m%d%H%M%S).txt"

# Check if URL is accessible
log_info "Checking URL accessibility..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$FULL_URL")
if [ "$HTTP_CODE" != "200" ]; then
    exit_error "URL returned HTTP code $HTTP_CODE. Please check if the URL is correct and accessible."
fi

log_success "URL is accessible. Starting performance tests..."

# Function to run a test and append to report
run_test() {
    local title=$1
    local command=$2
    
    echo -e "\n$title:" | tee -a "$REPORT_FILE"
    echo "-----------------------------------" | tee -a "$REPORT_FILE"
    eval "$command" | tee -a "$REPORT_FILE"
}

# Initialize report
echo "=== Performance Test Report ===" > "$REPORT_FILE"
echo "Environment: $ENV" >> "$REPORT_FILE"
echo "URL: $FULL_URL" >> "$REPORT_FILE"
echo "Date: $(date)" >> "$REPORT_FILE"
echo "====================================" >> "$REPORT_FILE"

# Basic latency test
run_test "🔍 Single Request Latency Test" "curl -s -w \"\nDNS Lookup: %{time_namelookup}s\nConnect: %{time_connect}s\nTLS Setup: %{time_appconnect}s\nTime to First Byte: %{time_starttransfer}s\nTotal Time: %{time_total}s\n\" -o /dev/null \"$FULL_URL\""

# Basic load test
run_test "🔄 Basic Load Test (50 requests, 5 concurrent)" "ab -n 50 -c 5 -k -H \"Accept-Encoding: gzip, deflate\" \"$FULL_URL\""

# Perform more detailed tests if confirmed
if confirm_action "Run more comprehensive performance tests?"; then
    # Medium load test
    run_test "📊 Medium Load Test (200 requests, 20 concurrent)" "ab -n 200 -c 20 -k -H \"Accept-Encoding: gzip, deflate\" \"$FULL_URL\""
    
    # Variable concurrency tests
    for c in 1 10 25 50; do
        run_test "👥 Concurrency Test ($c concurrent users)" "ab -n 100 -c $c -k -H \"Accept-Encoding: gzip, deflate\" \"$FULL_URL\""
    done
    
    # Detailed timing breakdown
    run_test "⏱️ Detailed Timing Analysis" "curl -s -w \"\nTime Breakdown:\n---------------\nDNS Lookup:        %{time_namelookup}s\nTCP Connect:       %{time_connect}s\nTLS Handshake:     %{time_appconnect}s\nTime to First Byte: %{time_starttransfer}s\nContent Transfer:  %{time_total}s\n\nRequest Size:     %{size_request} bytes\nHeader Size:      %{size_header} bytes\nDownload Size:    %{size_download} bytes\nTotal Size:       %{size_total} bytes\n\" -o /dev/null \"$FULL_URL\""
    
    # Test with keepalive
    run_test "🔌 Keep-Alive Connection Test" "ab -n 100 -c 10 -k -H \"Connection: keep-alive\" \"$FULL_URL\""
    
    # Test without keepalive
    run_test "🔌 Non-Keep-Alive Connection Test" "ab -n 100 -c 10 -H \"Connection: close\" \"$FULL_URL\""
fi

# Offer intensive test with warning
if confirm_action "⚠️ WARNING: Run intensive load test? This may affect server performance."; then
    # Ask for custom values or use defaults
    echo -e "${YELLOW}Enter number of requests [1000]:${NC}"
    read custom_requests
    requests=${custom_requests:-1000}
    
    echo -e "${YELLOW}Enter number of concurrent users [50]:${NC}"
    read custom_concurrency
    concurrency=${custom_concurrency:-50}
    
    run_test "🔥 Intensive Load Test ($requests requests, $concurrency concurrent)" "ab -n $requests -c $concurrency -k -H \"Accept-Encoding: gzip, deflate\" \"$FULL_URL\""
fi

log_success "Performance tests completed. Report saved to $REPORT_FILE"

# Ask if user wants to open the report
if command -v less &> /dev/null; then
    if confirm_action "Do you want to view the full report now?"; then
        less "$REPORT_FILE"
    fi
fi