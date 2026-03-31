# API Command - Quick Start Guide

## Overview

The `api` command in `deyecli.py` exposes all CLI commands as **HTTP REST endpoints**, making it easy to integrate with:
- **Home Assistant** (remote control of battery charging)
- **Node-RED** (automation flows)
- **Mobile apps** (custom integrations)
- **Third-party home automation systems**

## Quick Start

### 1. Start the API Server

```bash
./deyecli.py api
```

This starts the server on `http://0.0.0.0:8000` (all interfaces, port 8000)

### 2. Test an Endpoint

In another terminal:

```bash
curl -X GET "http://localhost:8000/api/station/list" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3. Integrate with Home Assistant

See [homeassistant_example.yaml](homeassistant_example.yaml) for a complete Home Assistant configuration example.

## How It Works

```
┌─────────────────────────┐
│   Home Assistant        │  ← Remote instance
│   (or other app)        │
└────────────┬────────────┘
             │
             │ HTTP Request
             │ e.g., POST /api/battery/parameter/update
             │
             ▼
┌─────────────────────────────────────────┐
│   deyecli.py (HTTP REST server)         │  ← localhost:8000
│   ┌─────────────────────────────────┐   │
│   │ HTTP Request Handler             │   │
│   └────────────┬────────────────────┘   │
│                │                         │
│                ▼                         │
│   ┌─────────────────────────────────┐   │
│   │ Route to CLI command             │   │
│   │ (e.g., battery-parameter-update) │   │
│   └────────────┬────────────────────┘   │
│                │                         │
└────────────────┼─────────────────────────┘
                 │
                 ▼
        ┌─────────────────────┐
        │  Deye Cloud API     │
        │  (REST endpoints)   │
        └─────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| **deyecli.py** | Unified CLI + integrated HTTP REST server |
| **README_API.md** | Complete API documentation with all endpoints |
| **homeassistant_example.yaml** | Home Assistant integration template |
| **test_api.sh** | Simple test script for API endpoints |

## Command Usage

```bash
# Start server on default port (8000)
./deyecli.py api

# Start on custom port
./deyecli.py api --port 9000

# Start on custom host and port
./deyecli.py api --host 192.168.1.100 --port 8080
```

## Available Endpoints

- `POST /api/token` - Get access token
- `GET /api/station/list` - List all stations
- `GET /api/station/latest` - Get station real-time data
- `GET /api/device/latest` - Get device raw data
- `GET /api/config/battery` - Read battery config
- `GET /api/config/system` - Read system config
- `POST /api/battery/parameter/update` - Update battery parameters
- `POST /api/solar-charge-cron` - Generate solar charge automation

## Authentication

Pass your bearer token via the `Authorization` header:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/station/list
```

Or in the request body:

```bash
curl -X POST http://localhost:8000/api/station/latest \
  -H "Content-Type: application/json" \
  -d '{"token": "YOUR_TOKEN", "station_id": "123456"}'
```

## Example Use Case: Reduce Battery Charge During Sunny Hours

Home Assistant automation using the API:

```yaml
automation:
  - alias: "Reduce charge when sunny"
    trigger:
      platform: time
      at: "10:00:00"
    action:
      - service: rest_command.deye_set_charge_current
        data:
          charge_current: "30"  # Reduce to 30A
```

## Testing

Use the provided test script:

```bash
./test_api.sh                    # Test on localhost:8000
./test_api.sh 192.168.1.100:8000 # Test on specific host:port
```

Set environment variables for full testing:

```bash
export DEYE_TOKEN="your-bearer-token"
export DEYE_DEVICE_SN="your-device-sn"
export DEYE_STATION_ID="your-station-id"
./test_api.sh
```

## Running as a Service (systemd)

Create `/etc/systemd/system/deye-api.service`:

```ini
[Unit]
Description=Deye CLI API Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/deyecli
ExecStart=/home/pi/deyecli/deyecli.py api --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Install and run:

```bash
sudo systemctl enable deye-api
sudo systemctl start deye-api
sudo systemctl status deye-api
```

View logs:

```bash
sudo journalctl -u deye-api -f
```

## Security Notes

⚠️ **Important:**

1. **Always use HTTPS in production** - Use a reverse proxy (nginx) with SSL/TLS
2. **Don't expose to the Internet** without proper authentication and firewall rules
3. **Secure your config file** - Run `chmod 600 ~/.config/deyecli/config`
4. **Use strong credentials** - Store tokens securely in Home Assistant
5. **Run as non-root** - Never run the server as root

## Troubleshooting

### Port already in use

```bash
lsof -i :8000  # Find process using the port
./deyecli.py api --port 9000  # Use a different port
```

### Server won't start

Check if Python 3 is available:

```bash
python3 --version
```

### API request times out

Increase curl timeout or check network connectivity:

```bash
curl --max-time 60 http://localhost:8000/api/station/list
```

## More Information

- See [README_API.md](README_API.md) for complete endpoint documentation
- See [homeassistant_example.yaml](homeassistant_example.yaml) for Home Assistant setup

---

**Status:** ✅ Ready for use

**Requirements:**
- Python 3.6+ (built-in `http.server`, `socket` modules)
- Valid Deye Cloud credentials configured in `~/.config/deyecli/config`
- Network access to Deye Cloud API

**Optional dependency:**
- `pip install requests` — recommended for better HTTP support
