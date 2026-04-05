[Buy Me a Coffee](https://buymeacoffee.com/numbor)

# deyecli
Python CLI for [Deye Cloud](https://developer.deyecloud.com/api) REST APIs, designed to control and monitor Deye photovoltaic inverters directly from the terminal. Includes an integrated HTTP REST API server.

---

> **⚠️ DISCLAIMER**  
> This software is provided "as is", without warranty of any kind, express or implied.  
> The author is not responsible for any damages, malfunctions, data loss, or issues arising from the use of this utility.  
> Use at your own risk and responsibility. It is recommended to thoroughly test commands before applying them in production environments.

---

## Requirements

| Tool | Notes |
|------|-------|
| `python3` ≥ 3.6 | available on any modern Linux |
| `requests` | optional — for HTTP calls (falls back to `curl` if not installed) |

## Installation

```bash
git clone <repo-url> deyecli
cd deyecli
chmod +x deyecli.py
```

Optionally, install the `requests` library for better HTTP support:

```bash
pip install requests
```

Optionally, add a symlink to your `PATH`:

```bash
ln -s "$PWD/deyecli.py" ~/.local/bin/deyecli
```

---

## Configuration

The script reads parameters from multiple sources, in descending order of precedence:

```
CLI flag  >  config file  >  environment variable  >  built-in defaults
```

### Config file

Default location: `~/.config/deyecli/config`  
Override with the `DEYE_CONFIG=/another/path` variable.

```bash
mkdir -p ~/.config/deyecli
cp config.example ~/.config/deyecli/config
$EDITOR ~/.config/deyecli/config
```

Example of a completed config file:

```ini
# Base URL — change region prefix if necessary
DEYE_BASE_URL=https://eu1-developer.deyecloud.com

# Application credentials (required for every call)
# Obtain them from https://developer.deyecloud.com
DEYE_APP_ID=<your-app-id>
DEYE_APP_SECRET=<your-app-secret>

# Login credentials — provide ONE of username, email, or mobile
DEYE_EMAIL=user@example.com

# Plaintext password — the script converts it to SHA-256 before sending
DEYE_PASSWORD=yourpassword

# Company ID for business token (leave empty for personal account)
DEYE_COMPANY_ID=

# Access token — automatically updated by the 'token' command
DEYE_TOKEN=

# Default device serial number used by config commands
DEYE_DEVICE_SN=

# Weather location for solar-charge-cron
DEYE_WEATHER_LAT=44.0637
DEYE_WEATHER_LON=12.4525

# Solar charge modulation defaults
DEYE_SOLAR_FORECAST_HOURS=12
DEYE_SOLAR_MIN_RADIATION=200
DEYE_SOLAR_LOW_CHARGE_CURRENT=5
DEYE_SOLAR_DEFAULT_CHARGE_CURRENT=
DEYE_SOLAR_PEAK_START=
DEYE_SOLAR_PEAK_END=
DEYE_SOLAR_RAMP_EXPONENT=4
DEYE_SOLAR_CRON_MINUTE=5
DEYE_SOLAR_CRON_FILE=~/.config/deyecli/solar-charge.cron
```

> **Security:** The file is read with a line-by-line parser, without `eval` or `source`.
> It is safe to insert values with special characters (JWT tokens, passwords with `%`, etc.).

### Environment variables

All config file keys can be passed as environment variables:

```bash
DEYE_APP_ID=xxx DEYE_APP_SECRET=yyy DEYE_EMAIL=me@example.com \
  DEYE_PASSWORD=mypassword ./deyecli.py token
```

---

## Commands

### `token` — Obtain an access token

`POST /v1.0/account/token`

Performs login and obtains an `accessToken`. If the call is successful **the token is automatically saved** in `DEYE_TOKEN` in the config file (via `jq`).

```bash
./deyecli.py token
```

**Required parameters:**

| Variable | Flag | Description |
|----------|------|-------------|
| `DEYE_APP_ID` | `--app-id` | Deye application ID |
| `DEYE_APP_SECRET` | `--app-secret` | Deye application secret |
| `DEYE_PASSWORD` | `--password` | Plaintext password (SHA-256 hashed) |
| `DEYE_EMAIL` *or* `DEYE_USERNAME` *or* `DEYE_MOBILE` | `--email` / `--username` / `--mobile` | Login identifier |

**Optional parameters:**

| Variable | Flag | Description |
|----------|------|-------------|
| `DEYE_COUNTRY_CODE` | `--country-code` | Required when using `DEYE_MOBILE` |
| `DEYE_COMPANY_ID` | `--company-id` | To obtain a business token |

**Example:**

```bash
./deyecli.py token
# → POST https://eu1-developer.deyecloud.com/v1.0/account/token?appId=...
# ✔  DEYE_TOKEN saved to /home/user/.config/deyecli/config
```

**Response (excerpt):**

```json
{
  "code": "1000000",
  "success": true,
  "accessToken": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expiresIn": "5183999",
  "tokenType": "bearer"
}
```

> **Note:** Deye returns the token with a `"Bearer "` prefix. The script removes it before saving and before each subsequent call, avoiding the double prefix `Bearer Bearer ...`.

---

### `config-battery` — Battery configuration parameters

`POST /v1.0/config/battery`

Reads battery configuration parameters for a hybrid inverter with storage.

The device serial number can be provided in three equivalent ways:

```bash
# 1. Positional argument
./deyecli.py config-battery 2401110313

# 2. Explicit flag
./deyecli.py config-battery --device-sn 2401110313

# 3. From config file (DEYE_DEVICE_SN)
./deyecli.py config-battery
```

**Required parameters:**

| Variable | Flag | Description |
|----------|------|-------------|
| `DEYE_TOKEN` | `--token` | Access token |
| `DEYE_DEVICE_SN` | `--device-sn` or positional arg | Hybrid inverter serial number |

**Response example:**

```json
{
  "code": "1000000",
  "success": true,
  "battCapacity": 100,
  "battLowCapacity": 20,
  "battShutDownCapacity": 10,
  "maxChargeCurrent": 50,
  "maxDischargeCurrent": 50
}
```

> **Warning:** The `deviceSn` must be that of a **hybrid inverter** (with battery), not the collector/logger. To find the correct serial number, use the Deye app or the `/v1.0/device/list` API.

---

### `config-system` — System work mode parameters

`POST /v1.0/config/system`

Reads the current system work mode, energy management pattern, and power limits configured for a device.

```bash
# Positional argument
./deyecli.py config-system 2401110313

# Explicit flag
./deyecli.py config-system --device-sn 2401110313

# From config file (DEYE_DEVICE_SN)
./deyecli.py config-system
```

**Required parameters:**

| Variable | Flag | Description |
|----------|------|-------------|
| `DEYE_TOKEN` | `--token` | Access token |
| `DEYE_DEVICE_SN` | `--device-sn` or positional arg | Device serial number |

**Response example:**

```json
{
  "code": "1000000",
  "success": true,
  "systemWorkMode": "SELLING_FIRST",
  "energyPattern": "BATTERY_FIRST",
  "maxSellPower": 6000,
  "maxSolarPower": 8000,
  "zeroExportPower": 0
}
```

**Possible `systemWorkMode` values:**

| Value | Description |
|-------|-------------|
| `SELLING_FIRST` | Sells excess energy to the grid |
| `ZERO_EXPORT_TO_LOAD` | No export, only covers loads |
| `ZERO_EXPORT_TO_CT` | Zero export measured via CT (current transformer) |

---

### `battery-parameter-update` — Set a battery parameter

`POST /v1.0/order/battery/parameter/update`

Sends a control command to set the value of a single battery parameter. The call returns an `orderId` representing the queued command; the device executes it as soon as it comes online.

```bash
# Set maximum charge current to 50 A
./deyecli.py battery-parameter-update \
    --param-type MAX_CHARGE_CURRENT \
    --value 50

# With explicit device SN
./deyecli.py battery-parameter-update \
    --device-sn 2401110313 \
    --param-type MAX_DISCHARGE_CURRENT \
    --value 40

# Device SN as positional argument
./deyecli.py battery-parameter-update 2401110313 \
    --param-type BATT_LOW \
    --value 15
```

**Required parameters:**

| Variable | Flag | Description |
|----------|------|-------------|
| `DEYE_TOKEN` | `--token` | Access token |
| `DEYE_DEVICE_SN` | `--device-sn` or positional arg | Device serial number |
| — | `--param-type <TYPE>` | Parameter type (see table below) |
| — | `--value <integer>` | Value to set |

**Parameter types (`--param-type`):**

| Value | Description |
|-------|-------------|
| `MAX_CHARGE_CURRENT` | Maximum charge current (A) |
| `MAX_DISCHARGE_CURRENT` | Maximum discharge current (A) |
| `GRID_CHARGE_AMPERE` | Grid charge current (A) |
| `BATT_LOW` | Low battery threshold / minimum SoC (%) |

> **API Note:** The JSON key is `paramterType` (typo in the Deye API, missing the second `e`). The script handles this automatically.

**Response example:**

```json
{
  "code": "1000000",
  "success": true,
  "orderId": 987654,
  "connectionStatus": 1,
  "collectionTime": 1711093038,
  "requestId": "abc123"
}
```

`connectionStatus`: `0` = Offline, `1` = Online  
An `orderId` other than `null` confirms the command has been queued. When the device comes online, it executes it and updates the parameters.

---

### `solar-charge-cron` — Generate smart charge modulation crontab

Analyzes Open-Meteo hourly forecast and generates a day-specific crontab to modulate `MAX_CHARGE_CURRENT` in the morning.

Goal: keep battery charging slower in early sunny hours, so more production can be exported to the grid before peak hours.

How it works:

1. Detects sunny morning slots from `is_day`, `direct_radiation`, and weather code.
2. Auto-detects peak window from forecast hour with max direct radiation (unless manually forced).
3. Applies a ramp before peak:

  `charge = low + (max - low) * t^exp`

  where `t` goes from 0 to 1 and `exp` is `--ramp-exponent`.
4. During peak hours, restores full/default charge current.
5. Writes cron entries with date guard and optional direct install via `crontab`.

Curve behavior (`--ramp-exponent`):

- `1` = linear
- `2` = gentle early slope, later acceleration
- `4` = default (flatter morning, steeper near peak)
- `6+` = very flat, sharp rise near peak

Examples:

```bash
# Preview computed slots and generated cron (without writing file)
./deyecli.py solar-charge-cron --print-slots --dry-run

# Generate cron file and print full content
./deyecli.py solar-charge-cron --print-crontab

# Install generated crontab immediately
./deyecli.py solar-charge-cron --install-crontab

# Use a flatter curve to delay battery fill more aggressively
./deyecli.py solar-charge-cron --ramp-exponent 6 --install-crontab
```

Main options:

| Option | Description |
|--------|-------------|
| `--lat`, `--lon` | Forecast coordinates (fallback: `DEYE_WEATHER_LAT/LON`) |
| `--hours` | Forecast horizon (1-48) |
| `--min-radiation` | Radiation threshold for sunny slots (W/m²) |
| `--low-charge-current` | Morning minimum current (A) |
| `--default-charge-current` | Default/peak current (A), auto-detected if omitted |
| `--peak-start`, `--peak-end` | Peak window override (hour, 0-23); auto-detected if omitted |
| `--ramp-exponent` | Ramp curve exponent (`DEYE_SOLAR_RAMP_EXPONENT`, default `4`) |
| `--minute` | Cron minute for generated entries |
| `--cron-file` | Output cron file path |
| `--print-slots` | Print weather/decision table |
| `--print-crontab` | Print generated cron content after write |
| `--dry-run` | Print cron to stdout without writing file |
| `--show-config` | Print effective solar-charge-cron config |
| `--install-crontab` | Install generated cron with `crontab <file>` |

Notes:

- Generated cron commands read config via `DEYE_CONFIG='<config-file>'`.
- `--device-sn` is not required in generated cron lines: it is read from `DEYE_DEVICE_SN` in config.
- Command logs are appended to `/tmp/deyecli.log`.

---

## Typical workflow

```bash
# 1. Initial configuration
cp config.example ~/.config/deyecli/config
$EDITOR ~/.config/deyecli/config   # insert APP_ID, APP_SECRET, EMAIL, PASSWORD

# 2. Login — token is automatically saved to config
./deyecli.py token

# 3. Insert your inverter's serial number in the config
#    (DEYE_DEVICE_SN=<serial>)

# 4. Read battery configuration
./deyecli.py config-battery
```

---

## Global options

All options can appear before or after the command name:

| Flag | Variable | Description |
|------|----------|-------------|
| `--base-url <url>` | `DEYE_BASE_URL` | API base URL |
| `--app-id <id>` | `DEYE_APP_ID` | Application ID |
| `--app-secret <secret>` | `DEYE_APP_SECRET` | Application secret |
| `--username <name>` | `DEYE_USERNAME` | Login username |
| `--email <email>` | `DEYE_EMAIL` | Login email |
| `--mobile <number>` | `DEYE_MOBILE` | Mobile number |
| `--country-code <code>` | `DEYE_COUNTRY_CODE` | International prefix (required with `--mobile`) |
| `--password <pass>` | `DEYE_PASSWORD` | Plaintext password (SHA-256 hashed before sending) |
| `--company-id <id>` | `DEYE_COMPANY_ID` | Company ID for business token |
| `--token <bearer>` | `DEYE_TOKEN` | Access token |
| `--device-sn <sn>` | `DEYE_DEVICE_SN` | Device serial number |
| `--print-query` | `DEYE_PRINT_QUERY` | Print all outgoing HTTP requests |
| `-h, --help` | | Show help |

Example:

```bash
./deyecli.py station-list --print-query
# → POST https://eu1-developer.deyecloud.com/v1.0/station/list
```

---

## Supported regions

| Region | Base URL |
|--------|----------|
| EU1 (default) | `https://eu1-developer.deyecloud.com` |

For other regions, update `DEYE_BASE_URL` in the config or pass `--base-url`.

---

## References

- [Deye Cloud Developer Portal](https://developer.deyecloud.com)
- [Deye OpenAPI Swagger (EU1)](https://eu1-developer.deyecloud.com/v2/api-docs)
- [Official sample code (GitHub)](https://github.com/DeyeCloudDevelopers/deye-openapi-client-sample-code)

---

## Support the project

If this tool is useful to you, buy me a coffee ☕

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-numbor-yellow?logo=buy-me-a-coffee&logoColor=white)](https://buymeacoffee.com/numbor)