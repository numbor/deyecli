# Deye API Server Documentation

## Overview

The Deye API Server exposes all CLI commands as RESTful HTTP endpoints, making it easy to integrate with remote platforms like **Home Assistant**, **Node-RED**, automation scripts, and other applications.

## Features

- **Full HTTP REST API** for all deyecli commands
- **Automatic parameter mapping** from HTTP requests to CLI arguments
- **Bearer token authentication** support via `Authorization: Bearer <token>` header
- **Flexible configuration** via environment variables and config files
- **Lightweight Python server** using built-in libraries (no external dependencies)

## Starting the Server

### Basic Usage

```bash
./deyecli.sh api
```

Starts the server on `0.0.0.0:8000` (all interfaces, port 8000)

### Custom Host and Port

```bash
./deyecli.sh api --host localhost --port 9000
```

Binds to `localhost:9000` (only accessible from this machine)

### Custom API Script Location

```bash
./deyecli.sh api --api-script /path/to/api_server.py --port 8080
```

## API Endpoints

All endpoints accept JSON request bodies and return JSON responses.

### Authentication

Include Bearer token in the `Authorization` header:

```bash
Authorization: Bearer YOUR_ACCESS_TOKEN
```

Alternatively, pass the token in the request body:

```json
{
  "token": "YOUR_ACCESS_TOKEN"
}
```

---

## Endpoint Reference

### 1. Get Access Token

**Endpoint:** `POST /api/token`

**Description:** Obtain an access token using credentials

**Request:**
```bash
curl -X POST http://localhost:8000/api/token \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": "your-app-id",
    "app_secret": "your-app-secret",
    "email": "your-email@example.com",
    "password": "your-password"
  }'
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "token",
  "data": {
    "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "expiresIn": 86400
  }
}
```

---

### 2. List Stations

**Endpoint:** `GET /api/station/list`

**Description:** Fetch all stations under the account

**Request:**
```bash
curl -X GET "http://localhost:8000/api/station/list" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "station-list",
  "data": {
    "stations": [
      {
        "stationId": "123456",
        "name": "Home Solar",
        "batterySOC": 87,
        "generationPower": 5230,
        "batteryPower": -500
      }
    ]
  }
}
```

---

### 3. Get Latest Station Data

**Endpoint:** `GET /api/station/latest`

**Description:** Fetch real-time data for a specific station

**Request:**
```bash
curl -X GET "http://localhost:8000/api/station/latest" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"station_id": "123456"}'
```

Or as query string:
```bash
curl -X GET "http://localhost:8000/api/station/latest?station_id=123456" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "station-latest",
  "data": {
    "batterySOC": 87,
    "batteryPower": -500,
    "generationPower": 5230,
    "gridPower": 4730,
    "loadsPower": 0
  }
}
```

---

### 4. Get Latest Device Data

**Endpoint:** `GET /api/device/latest`

**Description:** Fetch raw measure-point data for a device

**Request:**
```bash
curl -X GET "http://localhost:8000/api/device/latest" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"device_sn": "DEVICE_SERIAL_NUMBER"}'
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "device-latest",
  "data": {
    "measurePoints": {
      "system_mode": 0,
      "battery_power": -500,
      "pv1_voltage": 350
    }
  }
}
```

---

### 5. Read Battery Configuration

**Endpoint:** `GET /api/config/battery`

**Description:** Read battery configuration parameters

**Request:**
```bash
curl -X GET "http://localhost:8000/api/config/battery" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"device_sn": "DEVICE_SERIAL_NUMBER"}'
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "config-battery",
  "data": {
    "MAX_CHARGE_CURRENT": 100,
    "MAX_DISCHARGE_CURRENT": 100,
    "GRID_CHARGE_AMPERE": 50,
    "BATT_LOW": 10
  }
}
```

---

### 6. Read System Configuration

**Endpoint:** `GET /api/config/system`

**Description:** Read system work mode parameters

**Request:**
```bash
curl -X GET "http://localhost:8000/api/config/system" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"device_sn": "DEVICE_SERIAL_NUMBER"}'
```

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "config-system",
  "data": {
    "work_mode": 0,
    "feed_in_power": 0
  }
}
```

---

### 7. Update Battery Parameter

**Endpoint:** `POST /api/battery/parameter/update`

**Description:** Set a battery parameter value

**Request:**
```bash
curl -X POST "http://localhost:8000/api/battery/parameter/update" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "param_type": "MAX_CHARGE_CURRENT",
    "value": "50",
    "device_sn": "DEVICE_SERIAL_NUMBER"
  }'
```

**Valid Parameter Types:**
- `MAX_CHARGE_CURRENT`: 0-200 (A)
- `MAX_DISCHARGE_CURRENT`: 0-200 (A)
- `GRID_CHARGE_AMPERE`: 0-100 (A)
- `BATT_LOW`: 0-100 (%)

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "battery-parameter-update",
  "data": {}
}
```

---

### 8. Generate Solar Charge Cron

**Endpoint:** `POST /api/solar-charge-cron`

**Description:** Generate cron entries to reduce charging during sunny hours

**Request:**
```bash
curl -X POST "http://localhost:8000/api/solar-charge-cron" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lat": "44.0637",
    "lon": "12.4525",
    "hours": "12",
    "low_charge_current": "20",
    "device_sn": "DEVICE_SERIAL_NUMBER",
    "dry_run": true
  }'
```

**Optional Parameters:**
- `hours`: Forecast window in hours (default: 12)
- `cloud_max`: Max cloud cover 0-100% (default: 70)
- `min_radiation`: Min direct radiation W/m² (default: 200)
- `print_slots`: Show weather table (true/false)
- `restore_default_charge_current`: Restore default current after sunny hours (true/false)
- `dry_run`: Don't write file, just show content (true/false)

**Response:**
```json
{
  "status": 200,
  "success": true,
  "command": "solar-charge-cron",
  "data": {
    "raw_output": "# Deye CLI Solar Charge Cron Entries\n0 10 * * * deyecli.sh battery-parameter-update..."
  }
}
```

---

## Configuration

The API server automatically loads configuration from:

1. **Environment variables** (e.g., `DEYE_TOKEN`, `DEYE_APP_ID`)
2. **Config file** at `~/.config/deyecli/config` (or path specified in `DEYE_CONFIG`)

### Config File Example

Create `~/.config/deyecli/config`:

```bash
DEYE_BASE_URL="https://eu1-developer.deyecloud.com"
DEYE_APP_ID="your-app-id"
DEYE_APP_SECRET="your-app-secret"
DEYE_EMAIL="your-email@example.com"
DEYE_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
DEYE_DEVICE_SN="DEVICE_SERIAL_NUMBER"
DEYE_STATION_ID="123456"
```

---

## Home Assistant Integration

### 1. Add REST Command

Add to `configuration.yaml`:

```yaml
rest_command:
  deye_get_battery_soc:
    url: "http://localhost:8000/api/station/latest"
    method: GET
    headers:
      Authorization: "Bearer {{ state_attr('input_text.deye_token', 'value') }}"
    payload: '{"station_id": "YOUR_STATION_ID"}'
    content_type: "application/json"

  deye_set_charge_current:
    url: "http://localhost:8000/api/battery/parameter/update"
    method: POST
    headers:
      Authorization: "Bearer {{ state_attr('input_text.deye_token', 'value') }}"
      Content-Type: "application/json"
    payload: '{"param_type": "MAX_CHARGE_CURRENT", "value": "{{ value }}", "device_sn": "YOUR_DEVICE_SN"}'
```

### 2. Create Template Sensors

```yaml
template:
  - sensor:
      - name: "Battery SOC"
        state: "{{ state_attr('rest_command.deye_get_battery_soc', 'data').data.batterySOC }}"
        unit_of_measurement: "%"

      - name: "Battery Power"
        state: "{{ state_attr('rest_command.deye_get_battery_soc', 'data').data.batteryPower }}"
        unit_of_measurement: "W"
```

### 3. Create Automations

```yaml
automation:
  - alias: "Reduce battery charge when sunny"
    trigger:
      platform: time
      at: "10:00:00"
    action:
      service: rest_command.deye_set_charge_current
      data:
        value: "20"

  - alias: "Restore normal charge current"
    trigger:
      platform: time
      at: "17:00:00"
    action:
      service: rest_command.deye_set_charge_current
      data:
        value: "100"
```

---

## Error Handling

All error responses include status codes and error messages:

### 404 Not Found
```json
{
  "status": 404,
  "error": "Endpoint not found: /api/invalid",
  "available_endpoints": [...]
}
```

### 400 Bad Request
```json
{
  "status": 400,
  "success": false,
  "command": "token",
  "error": "Missing required parameter: password",
  "exit_code": 2
}
```

### 500 Server Error
```json
{
  "status": 500,
  "error": "Error executing command: timeout",
  "command": "station-latest"
}
```

---

## Running as a Service

### systemd Service (Linux)

Create `/etc/systemd/system/deye-api.service`:

```ini
[Unit]
Description=Deye CLI API Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/deyecli
ExecStart=/home/pi/deyecli/deyecli.sh api --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable deye-api
sudo systemctl start deye-api
sudo systemctl status deye-api
```

View logs:
```bash
sudo journalctl -u deye-api -f
```

---

## Troubleshooting

### Server won't start

Check if port is already in use:
```bash
lsof -i :8000
netstat -tulpn | grep 8000
```

Use a different port:
```bash
./deyecli.sh api --port 9000
```

### API requests timeout

Increase timeout in request or check network connectivity:
```bash
curl --max-time 60 http://localhost:8000/api/station/list
```

### Authentication fails

1. Verify token is valid: `./deyecli.sh token`
2. Check config file permissions: `chmod 600 ~/.config/deyecli/config`
3. Ensure token is passed correctly in `Authorization` header

---

## Performance Notes

- The server processes one request at a time (sequential)
- API command timeout is 60 seconds per request
- Multiple clients will queue requests
- For high-volume requests, consider deploying multiple instances on different ports

---

## Security Recommendations

1. **Always use HTTPS** in production (consider using a reverse proxy like nginx)
2. **Restrict network access** - don't expose to the Internet without authentication
3. **Use strong API credentials** in config file
4. **Restrict file permissions**: `chmod 600 ~/.config/deyecli/config`
5. **Run as non-root user** (never run as root)
6. **Consider using firewall rules** to limit access to trusted IPs

---

## Support

For issues or feature requests, refer to the main deyecli documentation.
