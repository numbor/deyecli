#!/usr/bin/env bash
# =============================================================================
# deyecli - Deye Cloud API CLI
# https://developer.deyecloud.com/api
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Default configuration (overridable via environment variables or config file)
# ---------------------------------------------------------------------------
DEYE_BASE_URL="${DEYE_BASE_URL:-https://eu1-developer.deyecloud.com}"
DEYE_APP_ID="${DEYE_APP_ID:-}"
DEYE_APP_SECRET="${DEYE_APP_SECRET:-}"
DEYE_USERNAME="${DEYE_USERNAME:-}"
DEYE_EMAIL="${DEYE_EMAIL:-}"
DEYE_MOBILE="${DEYE_MOBILE:-}"
DEYE_COUNTRY_CODE="${DEYE_COUNTRY_CODE:-}"
DEYE_PASSWORD="${DEYE_PASSWORD:-}"      # plaintext; script will SHA256-hash it
DEYE_COMPANY_ID="${DEYE_COMPANY_ID:-}"
DEYE_TOKEN="${DEYE_TOKEN:-}"            # Bearer token from /token endpoint
DEYE_DEVICE_SN="${DEYE_DEVICE_SN:-}"   # Device serial number
DEYE_STATION_ID="${DEYE_STATION_ID:-}"  # Station ID (integer)

# Config file location (XDG-compliant)
CONFIG_FILE="${DEYE_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/deyecli/config}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Print to stderr
err() { echo "[ERROR] $*" >&2; }

# Require a binary to be on PATH
require() {
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            err "'$cmd' is required but not found in PATH."
            exit 1
        fi
    done
}

# Pretty-print JSON if jq is available, otherwise raw output
json_output() {
    if command -v jq &>/dev/null; then
        jq .
    else
        cat
    fi
}

# SHA-256 hash a string (no trailing newline)
sha256() {
    printf '%s' "$1" | sha256sum | awk '{print $1}'
}

# Normalize a token: strip leading "Bearer " prefix if present
bear_token() {
    local t="$1"
    t="${t#[Bb][Ee][Aa][Rr][Ee][Rr] }"
    printf '%s' "$t"
}

# Validate battery parameter value: check numeric type and range
# Returns 0 if valid, 1 if invalid (prints error to stderr)
validate_battery_param() {
    local param_type="$1"
    local value="$2"
    
    # Check if value is an integer
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        err "Parameter value must be a positive integer, got: '$value'"
        return 1
    fi
    
    # Check range based on parameter type
    case "$param_type" in
        MAX_CHARGE_CURRENT)
            if (( value > 200 )); then
                err "MAX_CHARGE_CURRENT must be ≤ 200, got: $value"
                return 1
            fi
            ;;
        MAX_DISCHARGE_CURRENT)
            if (( value > 200 )); then
                err "MAX_DISCHARGE_CURRENT must be ≤ 200, got: $value"
                return 1
            fi
            ;;
        GRID_CHARGE_AMPERE)
            if (( value > 100 )); then
                err "GRID_CHARGE_AMPERE must be ≤ 100, got: $value"
                return 1
            fi
            ;;
        BATT_LOW)
            if (( value > 100 )); then
                err "BATT_LOW must be ≤ 100 (%), got: $value"
                return 1
            fi
            ;;
    esac
    
    return 0
}

# Write or update a KEY=VALUE line in the config file (safe with any chars)
config_set() {
    local key="$1" value="$2"
    mkdir -p "$(dirname "$CONFIG_FILE")"
    [[ -f "$CONFIG_FILE" ]] || touch "$CONFIG_FILE"
    if grep -q "^[[:space:]]*${key}[[:space:]]*=" "$CONFIG_FILE"; then
        local tmp
        tmp="$(mktemp)"
        awk -v key="$key" -v val="$value" \
            'BEGIN{replaced=0}
             $0 ~ "^[[:space:]]*"key"[[:space:]]*=" { print key"="val; replaced=1; next }
             { print }
             END { if(!replaced) print key"="val }' \
            "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$CONFIG_FILE"
    fi
}

# Load config file if it exists.
# Parses KEY=VALUE lines manually — no eval/source, safe with special chars.
# Skips blank lines and full-line comments (#). Strips inline comments.
# Strips surrounding single or double quotes from values.
load_config() {
    [[ -f "$CONFIG_FILE" ]] || return 0
    local line key value
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip blank lines and comment lines
        [[ "$line" =~ ^[[:space:]]*$ ]]  && continue
        [[ "$line" =~ ^[[:space:]]*#  ]] && continue
        # Must match KEY=VALUE (key: letters, digits, underscore)
        [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        # Strip trailing inline comment (whitespace + #)
        value="${value%%[[:space:]]#*}"
        # Strip surrounding double quotes
        [[ "$value" =~ ^\"(.*)\"$ ]] && value="${BASH_REMATCH[1]}"
        # Strip surrounding single quotes
        [[ "$value" =~ ^\'(.*)\'$ ]] && value="${BASH_REMATCH[1]}"
        export "$key=$value"
    done < "$CONFIG_FILE"
}

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  token           Obtain an access token          (POST /v1.0/account/token)
  config-battery  Read battery config parameters  (POST /v1.0/config/battery)
                  Usage: config-battery [--device-sn <sn>] [<sn>]
  config-system              Read system work mode parameters  (POST /v1.0/config/system)
                             Usage: config-system [--device-sn <sn>] [<sn>]
  battery-parameter-update   Set a battery parameter value     (POST /v1.0/order/battery/parameter/update)
                             Usage: battery-parameter-update --param-type <TYPE> --value <n> [--device-sn <sn>] [<sn>]
                             param-type and valid ranges:
                               MAX_CHARGE_CURRENT:     0-200 (A)
                               MAX_DISCHARGE_CURRENT:  0-200 (A)
                               GRID_CHARGE_AMPERE:     0-100 (A)
                               BATT_LOW:               0-100 (%)
  station-list               Fetch station list under the account     (POST /v1.0/station/list)
                             Returns stationId, name, batterySOC, generationPower, etc.
  station-latest             Fetch latest real-time data of a station (POST /v1.0/station/latest)
                             Includes batteryPower (W), batterySOC, generationPower, gridPower, etc.
                             Usage: station-latest [--station-id <id>] [<id>]
  device-latest              Fetch latest raw measure-point data of a device (POST /v1.0/device/latest)
                             Usage: device-latest [--device-sn <sn>] [<sn>]

Global options (can also be set in $CONFIG_FILE or as env vars):
  --base-url <url>        API base URL  (DEYE_BASE_URL)
  --app-id <id>           Application ID (DEYE_APP_ID)
  --app-secret <secret>   Application secret (DEYE_APP_SECRET)
  --username <name>       Login username (DEYE_USERNAME)
  --email <email>         Login e-mail (DEYE_EMAIL)
  --mobile <number>       Login mobile number (DEYE_MOBILE)
  --country-code <code>   Country code for mobile login (DEYE_COUNTRY_CODE)
  --password <pass>       Plaintext password — will be SHA-256 hashed (DEYE_PASSWORD)
  --company-id <id>       Company ID for business token (DEYE_COMPANY_ID)
  --token <bearer>        Access token from /token endpoint (DEYE_TOKEN)
  --device-sn <sn>        Device serial number (DEYE_DEVICE_SN)
  --station-id <id>       Station ID integer (DEYE_STATION_ID)
  -h, --help              Show this help

Examples:
  # Obtain a token
  DEYE_APP_ID=xxx DEYE_APP_SECRET=yyy DEYE_EMAIL=me@example.com \\
    DEYE_PASSWORD=mypassword $(basename "$0") token

  # Read battery config (token via env, device SN as positional arg)
  DEYE_TOKEN=eyJ... $(basename "$0") config-battery MY_DEVICE_SN

  # Using a config file ($CONFIG_FILE)
  $(basename "$0") token
  $(basename "$0") config-battery
EOF
}

# ---------------------------------------------------------------------------
# Argument parser (modifies global DEYE_* variables)
# ---------------------------------------------------------------------------
parse_global_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --base-url)     DEYE_BASE_URL="$2";     shift 2 ;;
            --app-id)       DEYE_APP_ID="$2";       shift 2 ;;
            --app-secret)   DEYE_APP_SECRET="$2";   shift 2 ;;
            --username)     DEYE_USERNAME="$2";     shift 2 ;;
            --email)        DEYE_EMAIL="$2";        shift 2 ;;
            --mobile)       DEYE_MOBILE="$2";       shift 2 ;;
            --country-code) DEYE_COUNTRY_CODE="$2"; shift 2 ;;
            --password)     DEYE_PASSWORD="$2";     shift 2 ;;
            --company-id)   DEYE_COMPANY_ID="$2";   shift 2 ;;            --token)        DEYE_TOKEN="$2";       shift 2 ;;
            --device-sn)    DEYE_DEVICE_SN="$2";   shift 2 ;;
            --station-id)   DEYE_STATION_ID="$2";  shift 2 ;;
            -h|--help)      usage; exit 0 ;;
            -*)             err "Unknown option: $1"; usage; exit 1 ;;
            *)              break ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Command: token  →  POST /v1.0/account/token
# ---------------------------------------------------------------------------
cmd_token() {
    # Parse any remaining args (same global flags are accepted here too)
    parse_global_args "$@"

    # Validate mandatory parameters
    local missing=()
    [[ -z "$DEYE_APP_ID" ]]     && missing+=("DEYE_APP_ID / --app-id")
    [[ -z "$DEYE_APP_SECRET" ]] && missing+=("DEYE_APP_SECRET / --app-secret")
    [[ -z "$DEYE_PASSWORD" ]]   && missing+=("DEYE_PASSWORD / --password")

    # At least one login identifier required
    if [[ -z "$DEYE_USERNAME" && -z "$DEYE_EMAIL" && -z "$DEYE_MOBILE" ]]; then
        missing+=("one of DEYE_USERNAME / DEYE_EMAIL / DEYE_MOBILE")
    fi

    # Mobile requires country code
    if [[ -n "$DEYE_MOBILE" && -z "$DEYE_COUNTRY_CODE" ]]; then
        missing+=("DEYE_COUNTRY_CODE / --country-code (required when using mobile)")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    # SHA-256 hash the plaintext password
    local hashed_password
    hashed_password="$(sha256 "$DEYE_PASSWORD")"

    # Build the JSON body
    local body
    if command -v jq &>/dev/null; then
        body="$(jq -n \
            --arg appSecret    "$DEYE_APP_SECRET" \
            --arg password     "$hashed_password" \
            --arg username     "$DEYE_USERNAME" \
            --arg email        "$DEYE_EMAIL" \
            --arg mobile       "$DEYE_MOBILE" \
            --arg countryCode  "$DEYE_COUNTRY_CODE" \
            --arg companyId    "$DEYE_COMPANY_ID" \
            '{ appSecret: $appSecret, password: $password }
             | if $username    != "" then . + { username: $username }                               else . end
             | if $email       != "" then . + { email: $email }                                    else . end
             | if $mobile      != "" then . + { mobile: $mobile, countryCode: $countryCode }       else . end
             | if $companyId   != "" then . + { companyId: ($companyId | tonumber) }               else . end'
        )"
    else
        # Fallback: build JSON manually (no jq)
        local _json
        _json="{ \"appSecret\": \"${DEYE_APP_SECRET}\", \"password\": \"${hashed_password}\""
        [[ -n "$DEYE_USERNAME" ]]    && _json+=", \"username\": \"${DEYE_USERNAME}\""
        [[ -n "$DEYE_EMAIL" ]]       && _json+=", \"email\": \"${DEYE_EMAIL}\""
        [[ -n "$DEYE_MOBILE" ]]      && _json+=", \"mobile\": \"${DEYE_MOBILE}\", \"countryCode\": \"${DEYE_COUNTRY_CODE}\""
        [[ -n "$DEYE_COMPANY_ID" ]]  && _json+=", \"companyId\": ${DEYE_COMPANY_ID}"
        _json+=" }"
        body="$_json"
    fi

    local url="${DEYE_BASE_URL}/v1.0/account/token?appId=${DEYE_APP_ID}"

    echo "→ POST ${url}" >&2

    local response
    response="$(curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --data "$body")"

    printf '%s\n' "$response" | json_output

    # If successful, save the token to the config file
    local success
    success="$(printf '%s' "$response" | grep -o '"success":[^,}]*' | head -1 | cut -d: -f2 | tr -d ' "')"
    if [[ "$success" == "true" ]] && command -v jq &>/dev/null; then
        local token
        token="$(printf '%s' "$response" | jq -r '.accessToken')"
        token="$(bear_token "$token")"
        config_set "DEYE_TOKEN" "$token"
        echo "✔  DEYE_TOKEN saved to ${CONFIG_FILE}" >&2
    fi
}

# ---------------------------------------------------------------------------
# Command: config-battery  →  POST /v1.0/config/battery
# ---------------------------------------------------------------------------
cmd_config_battery() {
    # Parse flags; collect leftover positional args
    local device_sn="${DEYE_DEVICE_SN:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn) device_sn="$2"; shift 2 ;;
            --*)         parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)   usage; exit 0 ;;
            *)           [[ -z "$device_sn" ]] && device_sn="$1"; shift ;;
        esac
    done

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]   && missing+=("DEYE_TOKEN / --token")
    [[ -z "$device_sn" ]]    && missing+=("device serial number  (DEYE_DEVICE_SN / --device-sn / positional arg)")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    local body="{ \"deviceSn\": \"${device_sn}\" }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceSn: $deviceSn }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/config/battery"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data "$body" \
    | json_output
}

# ---------------------------------------------------------------------------
# Command: config-system  →  POST /v1.0/config/system
# ---------------------------------------------------------------------------
cmd_config_system() {
    local device_sn="${DEYE_DEVICE_SN:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn) device_sn="$2"; shift 2 ;;
            --*)         parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)   usage; exit 0 ;;
            *)           [[ -z "$device_sn" ]] && device_sn="$1"; shift ;;
        esac
    done

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]  && missing+=("DEYE_TOKEN / --token")
    [[ -z "$device_sn" ]]   && missing+=("device serial number  (DEYE_DEVICE_SN / --device-sn / positional arg)")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    local body="{ \"deviceSn\": \"${device_sn}\" }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceSn: $deviceSn }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/config/system"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data "$body" \
    | json_output
}

# ---------------------------------------------------------------------------
# Command: battery-parameter-update  →  POST /v1.0/order/battery/parameter/update
# ---------------------------------------------------------------------------
cmd_battery_parameter_update() {
    local device_sn="${DEYE_DEVICE_SN:-}"
    local param_type=""
    local value=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn)  device_sn="$2";  shift 2 ;;
            --param-type) param_type="$2"; shift 2 ;;
            --value)      value="$2";      shift 2 ;;
            --*)          parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)    usage; exit 0 ;;
            *)            [[ -z "$device_sn" ]] && device_sn="$1"; shift ;;
        esac
    done

    # Validate enum value
    local valid_types="MAX_CHARGE_CURRENT MAX_DISCHARGE_CURRENT GRID_CHARGE_AMPERE BATT_LOW"
    if [[ -n "$param_type" ]] && ! echo " $valid_types " | grep -qw "$param_type"; then
        err "Invalid --param-type '$param_type'. Valid values: $valid_types"
        exit 1
    fi

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]  && missing+=("DEYE_TOKEN / --token")
    [[ -z "$device_sn" ]]   && missing+=("device serial number  (DEYE_DEVICE_SN / --device-sn / positional arg)")
    [[ -z "$param_type" ]]  && missing+=("--param-type <TYPE>  (MAX_CHARGE_CURRENT | MAX_DISCHARGE_CURRENT | GRID_CHARGE_AMPERE | BATT_LOW)")
    [[ -z "$value" ]]       && missing+=("--value <integer>")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    # Validate parameter value (numeric + range check)
    if ! validate_battery_param "$param_type" "$value"; then
        exit 1
    fi

    require curl

    local body
    if command -v jq &>/dev/null; then
        # Note: Deye API uses 'paramterType' (typo in the API — single 'e')
        body="$(jq -n \
            --arg deviceSn   "$device_sn" \
            --arg paramType  "$param_type" \
            --argjson value  "$value" \
            '{ deviceSn: $deviceSn, paramterType: $paramType, value: $value }'
        )"
    else
        body="{ \"deviceSn\": \"${device_sn}\", \"paramterType\": \"${param_type}\", \"value\": ${value} }"
    fi

    local url="${DEYE_BASE_URL}/v1.0/order/battery/parameter/update"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data "$body" \
    | json_output
}

# ---------------------------------------------------------------------------
# Command: station-list  →  POST /v1.0/station/list
# ---------------------------------------------------------------------------
cmd_station_list() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --*)       parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            *)         shift ;;
        esac
    done

    local missing=()
    [[ -z "$DEYE_TOKEN" ]] && missing+=("DEYE_TOKEN / --token")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    local url="${DEYE_BASE_URL}/v1.0/station/list"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data '{}' \
    | json_output
}

# ---------------------------------------------------------------------------
# Command: station-latest  →  POST /v1.0/station/latest
# ---------------------------------------------------------------------------
cmd_station_latest() {
    local station_id="${DEYE_STATION_ID:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --station-id) station_id="$2"; shift 2 ;;
            --*)          parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)    usage; exit 0 ;;
            *)            [[ -z "$station_id" ]] && station_id="$1"; shift ;;
        esac
    done

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]   && missing+=("DEYE_TOKEN / --token")
    [[ -z "$station_id" ]]   && missing+=("station ID  (DEYE_STATION_ID / --station-id / positional arg)")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    local body="{ \"stationId\": ${station_id} }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --argjson stationId "$station_id" '{ stationId: $stationId }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/station/latest"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data "$body" \
    | json_output
}

# ---------------------------------------------------------------------------
# Command: device-latest  →  POST /v1.0/device/latest
# ---------------------------------------------------------------------------
cmd_device_latest() {
    local device_sn="${DEYE_DEVICE_SN:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn) device_sn="$2"; shift 2 ;;
            --*)         parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)   usage; exit 0 ;;
            *)           [[ -z "$device_sn" ]] && device_sn="$1"; shift ;;
        esac
    done

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]  && missing+=("DEYE_TOKEN / --token")
    [[ -z "$device_sn" ]]   && missing+=("device serial number  (DEYE_DEVICE_SN / --device-sn / positional arg)")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit 1
    fi

    require curl

    local body="{ \"deviceList\": [\"${device_sn}\"] }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceList: [$deviceSn] }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/device/latest"

    echo "→ POST ${url}" >&2

    curl --silent --show-error \
        --request POST \
        --url "$url" \
        --header "Content-Type: application/json" \
        --header "Accept: application/json" \
        --header "authorization: Bearer $(bear_token "${DEYE_TOKEN}")" \
        --data "$body" \
    | json_output
}

# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------
main() {
    load_config

    if [[ $# -eq 0 ]]; then
        usage
        exit 0
    fi

    local command="$1"
    shift

    # Consume global flags that appear before the command
    # (re-parse in case user put flags before the command)
    # The individual command handlers call parse_global_args again for flags
    # that appear after the command name.

    case "$command" in
        token)          cmd_token "$@" ;;
        config-battery)            cmd_config_battery "$@" ;;
        config-system)             cmd_config_system "$@" ;;
        battery-parameter-update)  cmd_battery_parameter_update "$@" ;;
        station-list)              cmd_station_list "$@" ;;
        station-latest)            cmd_station_latest "$@" ;;
        device-latest)             cmd_device_latest "$@" ;;
        -h|--help|help)            usage; exit 0 ;;
        *)
            err "Unknown command: '$command'"
            usage
            exit 1
            ;;
    esac
}

main "$@"
