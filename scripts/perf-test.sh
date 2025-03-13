#!/bin/bash
# perf-test.sh - Run performance tests
set -e

# Output colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check parameters
if [ "$#" -lt 1 ]; then
    echo -e "${RED}Error: Missing environment.${NC}"
    echo "Usage: $0 <environment> [path]"
    echo "Example: $0 staging /api/subscribe"
    exit 1
fi

ENV=$1
PATH_TO_TEST=${2:-"/"}

if [[ "$ENV" != "production" && "$ENV" != "staging" ]]; then
    echo -e "${RED}Error: Environment must be 'production' or 'staging'.${NC}"
    exit 1
fi

# Configure URL based on environment
if [ "$ENV" == "production" ]; then
    BASE_URL="https://mlorente.dev"
else
    BASE_URL="https://staging.mlorente.dev"
fi

FULL_URL="${BASE_URL}${PATH_TO_TEST}"

echo -e "${BLUE}Running performance tests on ${FULL_URL}...${NC}"

# Check if required tools are available
if ! command -v ab &> /dev/null; then
    echo -e "${RED}Error: Apache Benchmark (ab) is not installed.${NC}"
    echo "Please install it with: sudo apt-get install apache2-utils"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is not installed.${NC}"
    echo "Please install it with: sudo apt-get install curl"
    exit 1
fi

# Check if URL is accessible
echo -e "${YELLOW}Checking URL accessibility...${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$FULL_URL")
if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}Error: URL returned HTTP code $HTTP_CODE${NC}"
    echo "Please check if the URL is correct and accessible."
    exit 1
fi

echo -e "${GREEN}URL is accessible. Starting performance tests...${NC}"

# Run basic performance test
echo -e "\n${BLUE}Running basic load test (100 requests, 10 concurrent)...${NC}"
ab -n 100 -c 10 -k -H "Accept-Encoding: gzip, deflate" "$FULL_URL"

# Run latency test
echo -e "\n${BLUE}Running latency test...${NC}"
curl -s -w "\nDNS Lookup Time: %{time_namelookup}\nConnect Time: %{time_connect}\nTLS Handshake Time: %{time_appconnect}\nTime to First Byte: %{time_starttransfer}\nTotal Time: %{time_total}\n" -o /dev/null "$FULL_URL"

# Offer to run a more intensive test
echo -e "\n${YELLOW}Do you want to run a more intensive test (1000 requests, 50 concurrent)? (y/n)${NC}"
read run_intensive

if [[ "$run_intensive" == "y" || "$run_intensive" == "Y" ]]; then
    echo -e "${BLUE}Running intensive load test...${NC}"
    ab -n 1000 -c 50 -k -H "Accept-Encoding: gzip, deflate" "$FULL_URL"
fi

echo -e "${GREEN}Performance tests completed.${NC}"