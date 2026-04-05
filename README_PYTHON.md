# Deye CLI - Python

## Overview

`deyecli.py` is the main program used to interact with the Deye Cloud APIs, with an integrated HTTP REST server.

### Key Features

✅ **All Deye Cloud commands**
- Token, battery config, system config, parameter updates
- Station list and real-time data
- No `jq`, `curl`, or `bash` required

✅ **Integrated HTTP API server**
- REST endpoints for all commands
- Bearer token authentication support
- Configurable host and port

✅ **Advanced configuration management**
- XDG-compliant configuration file
- Environment variables
- CLI arguments (with precedence)
- Auto-detection and token saving

✅ **Complete functionality**
- SHA256 password hashing
- Retry logic with exponential backoff
- Configurable timeouts
- Debug mode
- Solar forecast via Open-Meteo

## Installation

```bash
# Make executable
chmod +x deyecli.py

# Install optional dependencies (recommended)
pip install requests
```

## Usage

### CLI Commands

#### 1. Get access token

```bash
./deyecli.py token \
  --app-id YOUR_APP_ID \
  --app-secret YOUR_APP_SECRET \
  --email your@email.com \
  --password yourpassword
```

The token is automatically saved to: `~/.config/deyecli/config`

#### 2. Read battery configuration

```bash
./deyecli.py config-battery DEVICE_SN
```

#### 3. Read system configuration

```bash
./deyecli.py config-system DEVICE_SN
```

#### 4. Update battery parameters

```bash
./deyecli.py battery-parameter-update \
  --param-type MAX_CHARGE_CURRENT \
  --value 20 \
  --device-sn DEVICE_SN
```

Supported parameters:
- `MAX_CHARGE_CURRENT`: 0-200 (A)
- `MAX_DISCHARGE_CURRENT`: 0-200 (A)
- `GRID_CHARGE_AMPERE`: 0-100 (A)
- `BATT_LOW`: 0-100 (%)

#### 5. List stations

```bash
./deyecli.py station-list
```

#### 6. Get latest station data

```bash
./deyecli.py station-latest STATION_ID
```

#### 7. Get latest device data

```bash
./deyecli.py device-latest DEVICE_SN
```

#### 8. Generate cron for solar charge modulation

This command is intended to run early in the day. It analyzes weather forecasts
and generates a crontab that modulates `MAX_CHARGE_CURRENT` hour by hour:
- **Morning** (first sunny slot → peak): gradual ramp from low current to default current.
- **Peak** (peak_start → peak_end): full charge (default).
- **After peak**: full charge (default).
- **Cloudy day**: no modulation, default current all day.

The ramp uses this formula:

`charge = low + (max - low) * t^exp`

where `t` goes from `0` to `1`, and `exp` is controlled by `--ramp-exponent`.

Typical `--ramp-exponent` behavior:
- `1`: linear
- `2`: smoother
- `4`: default (flatter in the morning, steeper near peak)
- `6+`: very flat, strong final ramp-up

If `--peak-start/--peak-end` are not provided, peak hours are auto-detected
from the hour with maximum forecasted `direct_radiation`.

```bash
./deyecli.py solar-charge-cron \
  --lat 44.0637 \
  --lon 12.4525 \
  --low-charge-current 5 \
  --ramp-exponent 4 \
  --print-slots \
  --dry-run
```

Options:
- `--lat`, `--lon`: GPS coordinates (required, or set `DEYE_WEATHER_LAT/LON`)
- `--hours`: Forecast hours (default: 12)
- `--min-radiation`: Minimum radiation W/m2 to consider an hour "sunny" (default: 200)
- `--low-charge-current`: Minimum morning current (default: 5 A)
- `--default-charge-current`: Default/maximum charge current (auto-detect if omitted)
- `--peak-start`: Peak charge start hour (auto-detect if omitted)
- `--peak-end`: Peak charge end hour (auto-detect if omitted)
- `--ramp-exponent`: Ramp curve exponent (default: 4)
- `--minute`: Cron minute (default: 5)
- `--cron-file`: Output cron file path
- `--print-slots`: Show hourly slot table with computed current
- `--print-crontab`: Print generated crontab content
- `--dry-run`: Show cron content without writing file
- `--show-config`: Show active configuration
- `--install-crontab`: Automatically install generated crontab

#### 9. Show configuration

```bash
./deyecli.py show-config
```

#### 10. Start HTTP API server

```bash
./deyecli.py api --host 0.0.0.0 --port 8000
```

### Global Options

```bash
./deyecli.py [GLOBAL_OPTIONS] <command> [COMMAND_OPTIONS]
```

Available global options:
- `--base-url`: API base URL (default: https://eu1-developer.deyecloud.com)
- `--app-id`: Application ID
- `--app-secret`: Application secret
- `--username`: Username
- `--email`: Email
- `--mobile`: Mobile number
- `--country-code`: Country code
- `--password`: Password (automatic hashing)
- `--company-id`: Company ID
- `--token`: Bearer token
- `--device-sn`: Device serial number
- `--station-id`: Station ID
- `--print-query`: Debug mode (prints curl commands)

## Configuration

### Configuration File

The program loads configuration from: `~/.config/deyecli/config`

Format:
```ini
DEYE_APP_ID="your-app-id"
DEYE_APP_SECRET="your-app-secret"
DEYE_EMAIL="your@email.com"
DEYE_TOKEN="bearer-token-xxx"
DEYE_WEATHER_LAT="44.0637"
DEYE_WEATHER_LON="12.4525"
DEYE_SOLAR_FORECAST_HOURS="12"
DEYE_SOLAR_MIN_RADIATION="200"
DEYE_SOLAR_LOW_CHARGE_CURRENT="5"
DEYE_SOLAR_DEFAULT_CHARGE_CURRENT=""
DEYE_SOLAR_PEAK_START=""
DEYE_SOLAR_PEAK_END=""
DEYE_SOLAR_RAMP_EXPONENT="4"
DEYE_SOLAR_CRON_MINUTE="5"
DEYE_SOLAR_CRON_FILE="~/.config/deyecli/solar-charge.cron"
```

### Environment Variables

All settings support `DEYE_`-prefixed environment variables:

```bash
export DEYE_APP_ID="xxx"
export DEYE_TOKEN="yyy"
./deyecli.py station-list
```

### Configuration Precedence

1. **CLI arguments** (highest priority)
2. **Configuration file** (`~/.config/deyecli/config`)
3. **Environment variables** (`DEYE_*`)
4. **Default values**

## HTTP API Server

### Start the Server

```bash
./deyecli.py api --host 0.0.0.0 --port 8000
```

### Available Endpoints

#### POST /api/token
Get access token
```bash
curl -X POST http://localhost:8000/api/token \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "xxx",
    "app_secret": "yyy",
    "email": "me@example.com",
    "password": "pass"
  }'
```

#### GET /api/station/list
List stations
```bash
curl -X GET http://localhost:8000/api/station/list \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/station/latest
Get latest station data
```bash
curl -X GET 'http://localhost:8000/api/station/latest?station_id=123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/device/latest
Get latest device data
```bash
curl -X GET 'http://localhost:8000/api/device/latest?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/config/battery
Battery configuration
```bash
curl -X GET 'http://localhost:8000/api/config/battery?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### GET /api/config/system
System configuration
```bash
curl -X GET 'http://localhost:8000/api/config/system?device_sn=ABC123' \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### POST /api/battery/parameter/update
Update battery parameter
```bash
curl -X POST http://localhost:8000/api/battery/parameter/update \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "device_sn": "ABC123",
    "param_type": "MAX_CHARGE_CURRENT",
    "value": 20
  }'
```

#### POST /api/solar-charge-cron
Generate solar charge modulation cron
```bash
curl -X POST http://localhost:8000/api/solar-charge-cron \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lat": "44.0637",
    "lon": "12.4525",
    "hours": "12",
    "min_radiation": "200",
    "low_charge_current": "20",
    "peak_start": "12",
    "peak_end": "14",
    "device_sn": "ABC123"
  }'
```

## Practical Examples

### 1. Full setup

```bash
# 1. Create configuration file
mkdir -p ~/.config/deyecli
cat > ~/.config/deyecli/config << EOF
DEYE_BASE_URL="https://eu1-developer.deyecloud.com"
DEYE_APP_ID="your-app-id"
DEYE_APP_SECRET="your-app-secret"
DEYE_EMAIL="your@email.com"
DEYE_DEVICE_SN="your-device-sn"
DEYE_STATION_ID="123"
DEYE_WEATHER_LAT="44.0637"
DEYE_WEATHER_LON="12.4525"
