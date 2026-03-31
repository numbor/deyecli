#!/bin/bash
# Simple script to test the Deye API server
# Usage: ./test_api.sh [host:port]

HOST_PORT="${1:-localhost:8000}"
BASE_URL="http://$HOST_PORT"

echo "==================== Deye API Server Test ===================="
echo "Target: $BASE_URL"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to test endpoint
test_endpoint() {
    local method="$1"
    local endpoint="$2"
    local data="$3"
    local token="${4:-}"
    
    echo -e "${YELLOW}Testing:${NC} $method $endpoint"
    
    local cmd="curl -s -X $method"
    if [[ -n "$token" ]]; then
        cmd="$cmd -H 'Authorization: Bearer $token'"
    fi
    if [[ -n "$data" ]]; then
        cmd="$cmd -H 'Content-Type: application/json' -d '$data'"
    fi
    cmd="$cmd '$BASE_URL$endpoint'"
    
    local response=$(eval "$cmd")
    local http_code=$(eval "curl -s -o /dev/null -w '%{http_code}' -X $method $([[ -n \"$token\" ]] && echo \"-H 'Authorization: Bearer $token'\") $([[ -n \"$data\" ]] && echo \"-H 'Content-Type: application/json' -d '$data'\") '$BASE_URL$endpoint'")
    
    if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
        echo -e "${GREEN}✓ HTTP $http_code${NC}"
    else
        echo -e "${RED}✗ HTTP $http_code${NC}"
    fi
    
    # Pretty print JSON if available
    if command -v jq >/dev/null 2>&1; then
        echo "$response" | jq '.' 2>/dev/null || echo "$response"
    else
        echo "$response"
    fi
    echo ""
}

# Check server is running
echo "Checking if server is running..."
if ! curl -s -f "$BASE_URL/api/station/list" >/dev/null 2>&1; then
    echo -e "${YELLOW}Note:${NC} Server may not be running or requires authentication"
    echo ""
fi

# Test 1: List stations (requires token)
echo "Test 1: List Stations"
test_endpoint "GET" "/api/station/list" "" "${DEYE_TOKEN:-}"
echo ""

# Test 2: Get device latest (requires token)  
echo "Test 2: Get Device Latest"
test_endpoint "GET" "/api/device/latest" "{\"device_sn\": \"$DEYE_DEVICE_SN\"}" "${DEYE_TOKEN:-}"
echo ""

# Test 3: Get battery config (requires token)
echo "Test 3: Get Battery Config"
test_endpoint "GET" "/api/config/battery" "{\"device_sn\": \"$DEYE_DEVICE_SN\"}" "${DEYE_TOKEN:-}"
echo ""

# Test 4: Get system config (requires token)
echo "Test 4: Get System Config"
test_endpoint "GET" "/api/config/system" "{\"device_sn\": \"$DEYE_DEVICE_SN\"}" "${DEYE_TOKEN:-}"
echo ""

# Test 5: Test token endpoint with dummy credentials (will likely fail but shows endpoint works)
echo "Test 5: Token Endpoint (without valid credentials)"
test_endpoint "POST" "/api/token" '{"app_id":"test","app_secret":"test","email":"test@test.com","password":"test"}'
echo ""

echo "==================== Test Complete ===================="
echo ""
echo "Environment variables to set for full testing:"
echo "  export DEYE_TOKEN='your-bearer-token'"
echo "  export DEYE_DEVICE_SN='your-device-sn'"
echo "  export DEYE_STATION_ID='your-station-id'"
echo ""
echo "Then run: ./test_api.sh [host:port]"
