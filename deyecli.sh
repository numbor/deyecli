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
DEYE_PRINT_QUERY="${DEYE_PRINT_QUERY:-false}"  # Print curl commands
DEYE_CONNECT_TIMEOUT="${DEYE_CONNECT_TIMEOUT:-10}"  # curl connect timeout (seconds)
DEYE_MAX_TIME="${DEYE_MAX_TIME:-30}"               # curl max time (seconds)
DEYE_RETRY_MAX="${DEYE_RETRY_MAX:-2}"              # number of retries after first attempt
DEYE_RETRY_DELAY="${DEYE_RETRY_DELAY:-1}"          # initial retry delay (seconds)

# Exit codes
EXIT_OK=0
EXIT_USAGE=2
EXIT_DEP=3
EXIT_AUTH=4
EXIT_NETWORK=5
EXIT_API=6

PRINT_QUERY=0

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
            exit "$EXIT_DEP"
        fi
    done
}

# Pretty-print JSON if jq is available, and add human-readable timestamps
# Finds fields with names containing "time" (case-insensitive) and if they contain
# a unix epoch timestamp (large number), adds a _readable field with ISO 8601 format
json_output() {
    if command -v jq &>/dev/null; then
        jq 'walk(
          if type == "object" then
            reduce keys[] as $key (
              .;
              if (($key | ascii_downcase) | contains("time")) and
                 (.[$key] | type == "number") and
                 (.[$key] > 1000000000) then
                .[$key + "_readable"] = (.[$key] | todate)
              else
                .
              end
            )
          else
            .
          end
        )'
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

# Parse common truthy values
is_truthy() {
    case "${1,,}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

# Validate integer values used by runtime networking settings
validate_non_negative_int() {
    local name="$1" value="$2"
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        err "$name must be a non-negative integer, got: '$value'"
        return 1
    fi
    return 0
}

validate_positive_int() {
    local name="$1" value="$2"
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        err "$name must be a positive integer, got: '$value'"
        return 1
    fi
    return 0
}

validate_runtime_settings() {
    validate_positive_int "DEYE_CONNECT_TIMEOUT" "$DEYE_CONNECT_TIMEOUT" || return 1
    validate_positive_int "DEYE_MAX_TIME" "$DEYE_MAX_TIME" || return 1
    validate_non_negative_int "DEYE_RETRY_MAX" "$DEYE_RETRY_MAX" || return 1
    validate_positive_int "DEYE_RETRY_DELAY" "$DEYE_RETRY_DELAY" || return 1
    return 0
}

# Validate station ID: positive integer
validate_station_id() {
    local station_id="$1"
    if ! [[ "$station_id" =~ ^[1-9][0-9]*$ ]]; then
        err "Station ID must be a positive integer, got: '$station_id'"
        return 1
    fi
    return 0
}

# Validate device serial number format (basic sanity checks)
validate_device_sn() {
    local device_sn="$1"
    if ! [[ "$device_sn" =~ ^[A-Za-z0-9_-]{6,32}$ ]]; then
        err "Device serial number format is invalid: '$device_sn'"
        return 1
    fi
    return 0
}

# Escape string to JSON string-safe representation (without surrounding quotes)
json_escape() {
    local text="$1"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
    text="${text//$'\n'/\\n}"
    text="${text//$'\r'/\\r}"
    text="${text//$'\t'/\\t}"
    printf '%s' "$text"
}

# Return success state from an API JSON response.
# If the field is missing, assume success (preserves compatibility).
json_response_success() {
    local response="$1"
    local success=""

    if command -v jq &>/dev/null; then
        success="$(printf '%s' "$response" | jq -r 'if has("success") then (.success|tostring) else "true" end' 2>/dev/null || true)"
    else
        success="$(printf '%s' "$response" | grep -o '"success"[[:space:]]*:[[:space:]]*[^,}]*' | head -1 | cut -d: -f2- | tr -d ' "' || true)"
        [[ -z "$success" ]] && success="true"
    fi

    [[ "${success,,}" == "true" ]]
}

# Extract accessToken from response JSON
json_extract_access_token() {
    local response="$1"
    local token=""

    if command -v jq &>/dev/null; then
        token="$(printf '%s' "$response" | jq -r '.accessToken // empty' 2>/dev/null || true)"
    else
        token="$(printf '%s' "$response" | sed -n 's/.*"accessToken"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    fi

    printf '%s' "$token"
}

# Redact sensitive headers from debug output
sanitize_header_for_log() {
    local header="$1"
    if [[ "${header,,}" == authorization:* ]]; then
        printf '%s' 'authorization: Bearer ***REDACTED***'
    else
        printf '%s' "$header"
    fi
}

# Wrapper for curl that optionally prints the full command line
deye_curl() {
    local -a args
    args=("$@")

    if [[ "$PRINT_QUERY" -eq 1 ]]; then
        local i arg formatted=()
        for ((i=0; i<${#args[@]}; i++)); do
            arg="${args[i]}"
            if [[ "$arg" == "--header" || "$arg" == "-H" ]]; then
                formatted+=("$(printf '%q' "$arg")")
                if (( i + 1 < ${#args[@]} )); then
                    i=$((i + 1))
                    formatted+=("$(printf '%q' "$(sanitize_header_for_log "${args[i]}")")")
                fi
                continue
            fi
            formatted+=("$(printf '%q' "$arg")")
        done
        echo "↪ curl ${formatted[*]}" >&2
    fi

    curl "${args[@]}"
}

# Execute a POST JSON request with retry/timeout/error classification.
# Prints raw JSON response to stdout on success.
api_post_json() {
    local url="$1"
    local body="$2"
    local auth_token="${3:-}"

    require curl
    if ! validate_runtime_settings; then
        return "$EXIT_USAGE"
    fi

    local -a curl_args
    curl_args=(
        --silent --show-error
        --connect-timeout "$DEYE_CONNECT_TIMEOUT"
        --max-time "$DEYE_MAX_TIME"
        --request POST
        --url "$url"
        --header "Content-Type: application/json"
        --header "Accept: application/json"
        --data "$body"
    )

    if [[ -n "$auth_token" ]]; then
        curl_args+=(--header "authorization: Bearer $(bear_token "$auth_token")")
    fi

    local max_attempts=$((DEYE_RETRY_MAX + 1))
    local attempt=1
    local delay="$DEYE_RETRY_DELAY"
    local raw=""
    local response=""
    local http_code="000"
    local curl_status=0

    while (( attempt <= max_attempts )); do
        set +e
        raw="$(deye_curl "${curl_args[@]}" --write-out $'\n%{http_code}')"
        curl_status=$?
        set -e

        if [[ "$raw" == *$'\n'* ]]; then
            http_code="${raw##*$'\n'}"
            response="${raw%$'\n'*}"
        else
            http_code="000"
            response="$raw"
        fi

        local should_retry=0
        local retry_reason=""
        if (( curl_status != 0 )); then
            should_retry=1
            retry_reason="network error (curl exit ${curl_status})"
        elif [[ "$http_code" =~ ^5[0-9][0-9]$ || "$http_code" == "429" || "$http_code" == "000" ]]; then
            should_retry=1
            retry_reason="HTTP ${http_code}"
        fi

        if (( should_retry == 1 && attempt < max_attempts )); then
            err "Transient error calling ${url}: ${retry_reason}. Retry ${attempt}/${DEYE_RETRY_MAX} in ${delay}s."
            sleep "$delay"
            attempt=$((attempt + 1))
            delay=$((delay * 2))
            continue
        fi

        break
    done

    if (( curl_status != 0 )); then
        err "Network error calling ${url} (curl exit ${curl_status})."
        [[ -n "$response" ]] && printf '%s\n' "$response" | json_output >&2 || true
        return "$EXIT_NETWORK"
    fi

    if [[ ! "$http_code" =~ ^2[0-9][0-9]$ ]]; then
        case "$http_code" in
            401|403)
                err "Authentication failed for ${url} (HTTP ${http_code})."
                [[ -n "$response" ]] && printf '%s\n' "$response" | json_output >&2 || true
                return "$EXIT_AUTH"
                ;;
            *)
                err "API request failed for ${url} (HTTP ${http_code})."
                [[ -n "$response" ]] && printf '%s\n' "$response" | json_output >&2 || true
                return "$EXIT_API"
                ;;
        esac
    fi

    if ! json_response_success "$response"; then
        err "API returned success=false for ${url}."
        printf '%s\n' "$response" | json_output >&2
        return "$EXIT_API"
    fi

    printf '%s' "$response"
    return "$EXIT_OK"
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
    local config_dir tmp old_umask
    config_dir="$(dirname "$CONFIG_FILE")"
    old_umask="$(umask)"
    umask 077

    tmp=""
    trap '[[ -n "${tmp:-}" && -f "$tmp" ]] && rm -f "$tmp"; umask "$old_umask"' RETURN

    mkdir -p "$config_dir"
    [[ -f "$CONFIG_FILE" ]] || : > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true

    tmp="$(mktemp "${CONFIG_FILE}.tmp.XXXXXX")"
    if grep -q "^[[:space:]]*${key}[[:space:]]*=" "$CONFIG_FILE"; then
        awk -v key="$key" -v val="$value" \
            'BEGIN{replaced=0}
             $0 ~ "^[[:space:]]*"key"[[:space:]]*=" { print key"="val; replaced=1; next }
             { print }
             END { if(!replaced) print key"="val }' \
            "$CONFIG_FILE" > "$tmp"
    else
        cat "$CONFIG_FILE" > "$tmp"
        printf '\n%s=%s\n' "$key" "$value" >> "$tmp"
    fi

    chmod 600 "$tmp" 2>/dev/null || true
    mv "$tmp" "$CONFIG_FILE"

    tmp=""
    umask "$old_umask"
    trap - RETURN
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
    --connect-timeout <s>   curl connect timeout in seconds (DEYE_CONNECT_TIMEOUT)
    --max-time <s>          curl max time in seconds (DEYE_MAX_TIME)
    --retry-max <n>         Number of retries for transient failures (DEYE_RETRY_MAX)
    --retry-delay <s>       Initial retry delay in seconds (DEYE_RETRY_DELAY)
    --print-query           Print curl commands with sensitive headers redacted
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
            --company-id)   DEYE_COMPANY_ID="$2";   shift 2 ;;
            --token)        DEYE_TOKEN="$2";       shift 2 ;;
            --device-sn)    DEYE_DEVICE_SN="$2";   shift 2 ;;
            --station-id)   DEYE_STATION_ID="$2";  shift 2 ;;
            --connect-timeout) DEYE_CONNECT_TIMEOUT="$2"; shift 2 ;;
            --max-time)     DEYE_MAX_TIME="$2";     shift 2 ;;
            --retry-max)    DEYE_RETRY_MAX="$2";    shift 2 ;;
            --retry-delay)  DEYE_RETRY_DELAY="$2";  shift 2 ;;
            --print-query)  PRINT_QUERY=1;           shift ;;
            -h|--help)      usage; exit 0 ;;
            -*)             err "Unknown option: $1"; usage; exit "$EXIT_USAGE" ;;
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
        exit "$EXIT_USAGE"
    fi

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
        # Fallback: build JSON manually with proper escaping (no jq)
        local _json
        _json="{\"appSecret\":\"$(json_escape "$DEYE_APP_SECRET")\",\"password\":\"$(json_escape "$hashed_password")\""
        [[ -n "$DEYE_USERNAME" ]]    && _json+=",\"username\":\"$(json_escape "$DEYE_USERNAME")\""
        [[ -n "$DEYE_EMAIL" ]]       && _json+=",\"email\":\"$(json_escape "$DEYE_EMAIL")\""
        [[ -n "$DEYE_MOBILE" ]]      && _json+=",\"mobile\":\"$(json_escape "$DEYE_MOBILE")\",\"countryCode\":\"$(json_escape "$DEYE_COUNTRY_CODE")\""
        if [[ -n "$DEYE_COMPANY_ID" ]]; then
            if ! [[ "$DEYE_COMPANY_ID" =~ ^[0-9]+$ ]]; then
                err "DEYE_COMPANY_ID must be a non-negative integer, got: '$DEYE_COMPANY_ID'"
                exit "$EXIT_USAGE"
            fi
            _json+=",\"companyId\":${DEYE_COMPANY_ID}"
        fi
        _json+="}"
        body="$_json"
    fi

    local url="${DEYE_BASE_URL}/v1.0/account/token?appId=${DEYE_APP_ID}"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" "$body")" || { local rc=$?; exit "$rc"; }

    printf '%s\n' "$response" | json_output

    # If successful, save the token to the config file
    if json_response_success "$response"; then
        local token
        token="$(json_extract_access_token "$response")"
        if [[ -n "$token" ]]; then
            token="$(bear_token "$token")"
            config_set "DEYE_TOKEN" "$token"
            echo "✔  DEYE_TOKEN saved to ${CONFIG_FILE}" >&2
        fi
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
            --print-query) PRINT_QUERY=1; shift ;;
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
        exit "$EXIT_USAGE"
    fi

    if ! validate_device_sn "$device_sn"; then
        exit "$EXIT_USAGE"
    fi

    local body="{ \"deviceSn\": \"${device_sn}\" }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceSn: $deviceSn }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/config/battery"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" "$body" "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
}

# ---------------------------------------------------------------------------
# Command: config-system  →  POST /v1.0/config/system
# ---------------------------------------------------------------------------
cmd_config_system() {
    local device_sn="${DEYE_DEVICE_SN:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn) device_sn="$2"; shift 2 ;;
            --print-query) PRINT_QUERY=1; shift ;;
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
        exit "$EXIT_USAGE"
    fi

    if ! validate_device_sn "$device_sn"; then
        exit "$EXIT_USAGE"
    fi

    local body="{ \"deviceSn\": \"${device_sn}\" }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceSn: $deviceSn }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/config/system"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" "$body" "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
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
            --print-query) PRINT_QUERY=1; shift ;;
            --*)          parse_global_args "$1" "$2"; shift 2 ;;
            -h|--help)    usage; exit 0 ;;
            *)            [[ -z "$device_sn" ]] && device_sn="$1"; shift ;;
        esac
    done

    # Validate enum value
    local valid_types="MAX_CHARGE_CURRENT MAX_DISCHARGE_CURRENT GRID_CHARGE_AMPERE BATT_LOW"
    if [[ -n "$param_type" ]] && ! echo " $valid_types " | grep -qw "$param_type"; then
        err "Invalid --param-type '$param_type'. Valid values: $valid_types"
        exit "$EXIT_USAGE"
    fi

    local missing=()
    [[ -z "$DEYE_TOKEN" ]]  && missing+=("DEYE_TOKEN / --token")
    [[ -z "$device_sn" ]]   && missing+=("device serial number  (DEYE_DEVICE_SN / --device-sn / positional arg)")
    [[ -z "$param_type" ]]  && missing+=("--param-type <TYPE>  (MAX_CHARGE_CURRENT | MAX_DISCHARGE_CURRENT | GRID_CHARGE_AMPERE | BATT_LOW)")
    [[ -z "$value" ]]       && missing+=("--value <integer>")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing required parameter(s):"
        for m in "${missing[@]}"; do err "  - $m"; done
        exit "$EXIT_USAGE"
    fi

    if ! validate_device_sn "$device_sn"; then
        exit "$EXIT_USAGE"
    fi

    # Validate parameter value (numeric + range check)
    if ! validate_battery_param "$param_type" "$value"; then
        exit "$EXIT_USAGE"
    fi

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

    local response
    response="$(api_post_json "$url" "$body" "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
}

# ---------------------------------------------------------------------------
# Command: station-list  →  POST /v1.0/station/list
# ---------------------------------------------------------------------------
cmd_station_list() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --print-query) PRINT_QUERY=1; shift ;;
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
        exit "$EXIT_USAGE"
    fi

    local url="${DEYE_BASE_URL}/v1.0/station/list"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" '{}' "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
}

# ---------------------------------------------------------------------------
# Command: station-latest  →  POST /v1.0/station/latest
# ---------------------------------------------------------------------------
cmd_station_latest() {
    local station_id="${DEYE_STATION_ID:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --station-id) station_id="$2"; shift 2 ;;
            --print-query) PRINT_QUERY=1; shift ;;
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
        exit "$EXIT_USAGE"
    fi

    if ! validate_station_id "$station_id"; then
        exit "$EXIT_USAGE"
    fi

    local body="{ \"stationId\": ${station_id} }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --argjson stationId "$station_id" '{ stationId: $stationId }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/station/latest"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" "$body" "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
}

# ---------------------------------------------------------------------------
# Command: device-latest  →  POST /v1.0/device/latest
# ---------------------------------------------------------------------------
cmd_device_latest() {
    local device_sn="${DEYE_DEVICE_SN:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --device-sn) device_sn="$2"; shift 2 ;;
            --print-query) PRINT_QUERY=1; shift ;;
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
        exit "$EXIT_USAGE"
    fi

    if ! validate_device_sn "$device_sn"; then
        exit "$EXIT_USAGE"
    fi

    local body="{ \"deviceList\": [\"${device_sn}\"] }"
    if command -v jq &>/dev/null; then
        body="$(jq -n --arg deviceSn "$device_sn" '{ deviceList: [$deviceSn] }')"
    fi

    local url="${DEYE_BASE_URL}/v1.0/device/latest"

    echo "→ POST ${url}" >&2

    local response
    response="$(api_post_json "$url" "$body" "$DEYE_TOKEN")" || { local rc=$?; exit "$rc"; }
    printf '%s\n' "$response" | json_output
}

# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------
main() {
    load_config

    if is_truthy "$DEYE_PRINT_QUERY"; then
        PRINT_QUERY=1
    fi

    if ! validate_runtime_settings; then
        exit "$EXIT_USAGE"
    fi

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
            exit "$EXIT_USAGE"
            ;;
    esac
}

main "$@"
