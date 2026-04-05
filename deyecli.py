#!/usr/bin/env python3
"""
Deye CLI - Python client and API server
Exposes Deye Cloud API commands as CLI and REST endpoints
https://developer.deyecloud.com/api
"""

import sys
import os
import json
import argparse
import hashlib
import logging
import subprocess
import http.server
import socketserver
import time
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import threading

try:
    import requests
except ImportError:
    requests = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DEP = 3

def _log(msg):
    """Print a message to stderr with a date/time prefix."""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] {msg}", file=sys.stderr)
EXIT_AUTH = 4
EXIT_NETWORK = 5
EXIT_API = 6


class DeyeConfig:
    """Configuration manager for Deye CLI"""
    
    def __init__(self):
        self.config_file = os.getenv(
            'DEYE_CONFIG',
            os.path.expanduser('~/.config/deyecli/config')
        )
        self.defaults = {
            'DEYE_BASE_URL': 'https://eu1-developer.deyecloud.com',
            'DEYE_APP_ID': '',
            'DEYE_APP_SECRET': '',
            'DEYE_USERNAME': '',
            'DEYE_EMAIL': '',
            'DEYE_MOBILE': '',
            'DEYE_COUNTRY_CODE': '',
            'DEYE_PASSWORD': '',
            'DEYE_COMPANY_ID': '',
            'DEYE_TOKEN': '',
            'DEYE_DEVICE_SN': '',
            'DEYE_STATION_ID': '',
            'DEYE_PRINT_QUERY': 'false',
            'DEYE_CONNECT_TIMEOUT': '10',
            'DEYE_MAX_TIME': '30',
            'DEYE_RETRY_MAX': '2',
            'DEYE_RETRY_DELAY': '1',
            'DEYE_WEATHER_LAT': '',
            'DEYE_WEATHER_LON': '',
            'DEYE_SOLAR_FORECAST_HOURS': '12',
            'DEYE_SOLAR_MIN_RADIATION': '200',
            'DEYE_SOLAR_LOW_CHARGE_CURRENT': '5',
            'DEYE_SOLAR_DEFAULT_CHARGE_CURRENT': '',
            'DEYE_SOLAR_PEAK_START': '',
            'DEYE_SOLAR_PEAK_END': '',
            'DEYE_SOLAR_RAMP_EXPONENT': '4',
            'DEYE_SOLAR_CRON_MINUTE': '5',
            'DEYE_SOLAR_CRON_FILE': os.path.expanduser('~/.config/deyecli/solar-charge.cron'),
        }
        # Initialize with environment variables
        self.config = {}
        for key, default in self.defaults.items():
            self.config[key] = os.getenv(key, default)
        
        # Load config file
        self.load_config_file()
    
    def load_config_file(self):
        """Load configuration from file"""
        if not os.path.exists(self.config_file):
            return
        
        try:
            with open(self.config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    # Parse KEY=VALUE
                    if '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Strip quotes
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    # Update config with loaded value
                    if key in self.config:
                        self.config[key] = value
        except Exception as e:
            logger.warning(f"Error loading config file {self.config_file}: {e}")
    
    def save_config(self, key: str, value: str):
        """Save a configuration value to file"""
        config_dir = os.path.dirname(self.config_file)
        os.makedirs(config_dir, exist_ok=True)
        
        # Read existing config
        existing = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            k, v = line.split('=', 1)
                            existing[k.strip()] = v.strip()
            except:
                pass
        
        # Update value
        existing[key] = value
        
        # Write config
        os.makedirs(config_dir, exist_ok=True)
        with open(self.config_file, 'w') as f:
            os.chmod(self.config_file, 0o600)
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        
        # Update runtime config
        self.config[key] = value
    
    def get(self, key: str, default: Optional[str] = None) -> str:
        """Get a config value"""
        value = self.config.get(key, default or '')
        return value
    
    def __getitem__(self, key: str) -> str:
        return self.config.get(key, '')


class DeyeAPI:
    """Deye Cloud API client"""
    
    def __init__(self, config: DeyeConfig):
        self.config = config
        self.print_query = self._is_truthy(config.get('DEYE_PRINT_QUERY'))
    
    @staticmethod
    def _is_truthy(value: str) -> bool:
        """Check if a value is truthy"""
        return value.lower() in ('true', '1', 'yes', 'on')
    
    @staticmethod
    def _sha256(text: str) -> str:
        """SHA256 hash a string"""
        return hashlib.sha256(text.encode()).hexdigest()
    
    @staticmethod
    def _normalize_token(token: str) -> str:
        """Strip Bearer prefix from token"""
        if token.lower().startswith('bearer '):
            return token[7:]
        return token
    
    def _log_query(self, method: str, url: str, headers: Optional[Dict] = None):
        """Log API query if debug enabled"""
        if self.print_query and headers:
            safe_headers = {}
            for k, v in headers.items():
                if k.lower() == 'authorization':
                    safe_headers[k] = 'Bearer ***REDACTED***'
                else:
                    safe_headers[k] = v
            logger.info(f"↪ {method} {url} {safe_headers}")
    
    def api_post_json(self, url: str, body: Dict, token: Optional[str] = None) -> Tuple[int, Dict]:
        """Execute a POST JSON request with retry logic"""
        
        if requests is None:
            # Fallback to subprocess curl
            return self._curl_post_json(url, body, token)
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        
        if token:
            token = self._normalize_token(token)
            headers['Authorization'] = f'Bearer {token}'
        
        self._log_query('POST', url, headers)
        
        connect_timeout = int(self.config.get('DEYE_CONNECT_TIMEOUT', '10'))
        max_time = int(self.config.get('DEYE_MAX_TIME', '30'))
        retry_max = int(self.config.get('DEYE_RETRY_MAX', '2'))
        retry_delay = int(self.config.get('DEYE_RETRY_DELAY', '1'))
        
        for attempt in range(retry_max + 1):
            try:
                response = requests.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=(connect_timeout, max_time)
                )
                
                # Check if response is successful
                if response.status_code >= 200 and response.status_code < 300:
                    try:
                        return response.status_code, response.json()
                    except:
                        return response.status_code, {'raw_output': response.text}
                
                # Retry on server error or rate limit
                if response.status_code >= 500 or response.status_code == 429:
                    if attempt < retry_max:
                        logger.error(
                            f"Transient error calling {url}: HTTP {response.status_code}. "
                            f"Retry {attempt + 1}/{retry_max} in {retry_delay}s."
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                
                # Return error response
                try:
                    return response.status_code, response.json()
                except:
                    return response.status_code, {'error': response.text}
            
            except requests.exceptions.Timeout:
                if attempt < retry_max:
                    logger.error(f"Timeout calling {url}. Retry {attempt + 1}/{retry_max} in {retry_delay}s.")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return 0, {'error': 'Connection timeout'}
            except Exception as e:
                if attempt < retry_max:
                    logger.error(f"Error calling {url}: {e}. Retry {attempt + 1}/{retry_max} in {retry_delay}s.")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return 0, {'error': str(e)}
        
        return 0, {'error': 'Max retries exceeded'}
    
    def _curl_post_json(self, url: str, body: Dict, token: Optional[str] = None) -> Tuple[int, Dict]:
        """Fallback: use curl subprocess for POST"""
        
        cmd = [
            'curl',
            '--silent', '--show-error',
            '--connect-timeout', self.config.get('DEYE_CONNECT_TIMEOUT', '10'),
            '--max-time', self.config.get('DEYE_MAX_TIME', '30'),
            '--request', 'POST',
            '--url', url,
            '--header', 'Content-Type: application/json',
            '--header', 'Accept: application/json',
            '--data', json.dumps(body),
            '--write-out', '\n%{http_code}'
        ]
        
        if token:
            token = self._normalize_token(token)
            cmd.extend(['--header', f'Authorization: Bearer {token}'])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                return 0, {'error': result.stderr or 'Command failed'}
            
            lines = result.stdout.rsplit('\n', 1)
            if len(lines) == 2:
                response_text = lines[0]
                http_code = int(lines[1])
            else:
                response_text = result.stdout
                http_code = 200
            
            try:
                return http_code, json.loads(response_text)
            except:
                return http_code, {'raw_output': response_text}
        
        except Exception as e:
            return 0, {'error': str(e)}


class DeyCLI:
    """Deye CLI command handler"""
    
    def __init__(self, config: DeyeConfig):
        self.config = config
        self.api = DeyeAPI(config)
    
    @staticmethod
    def _validate_positive_int(name: str, value: str) -> bool:
        """Validate positive integer"""
        if not value or not value.isdigit() or int(value) == 0:
            _log(f"[ERROR] {name} must be a positive integer, got: '{value}'")
            return False
        return True
    
    @staticmethod
    def _validate_non_negative_int(name: str, value: str) -> bool:
        """Validate non-negative integer"""
        if not value or not value.isdigit():
            _log(f"[ERROR] {name} must be a non-negative integer, got: '{value}'")
            return False
        return True
    
    @staticmethod
    def _validate_float_range(name: str, value: str, min_val: float, max_val: float) -> bool:
        """Validate float in range"""
        try:
            fval = float(value)
            if fval < min_val or fval > max_val:
                _log(f"[ERROR] {name} must be between {min_val} and {max_val}, got: '{value}'")
                return False
            return True
        except:
            _log(f"[ERROR] {name} must be a number, got: '{value}'")
            return False
    
    def _validate_device_sn(self, device_sn: str) -> bool:
        """Validate device serial number"""
        if not re.match(r'^[A-Za-z0-9_-]{6,32}$', device_sn):
            _log(f"[ERROR] Device serial number format is invalid: '{device_sn}'")
            return False
        return True
    
    def _validate_station_id(self, station_id: str) -> bool:
        """Validate station ID"""
        if not re.match(r'^[1-9][0-9]*$', station_id):
            _log(f"[ERROR] Station ID must be a positive integer, got: '{station_id}'")
            return False
        return True
    
    def _validate_battery_param(self, param_type: str, value: str) -> bool:
        """Validate battery parameter"""
        if not value.isdigit():
            _log(f"[ERROR] Parameter value must be a positive integer, got: '{value}'")
            return False
        
        ivalue = int(value)
        ranges = {
            'MAX_CHARGE_CURRENT': 200,
            'MAX_DISCHARGE_CURRENT': 200,
            'GRID_CHARGE_AMPERE': 100,
            'BATT_LOW': 100,
        }
        
        if param_type in ranges and ivalue > ranges[param_type]:
            _log(f"[ERROR] {param_type} must be ≤ {ranges[param_type]}, got: {ivalue}")
            return False
        
        return True
    
    def cmd_token(self, args):
        """Obtain access token"""
        
        for key in ['DEYE_APP_ID', 'DEYE_APP_SECRET', 'DEYE_PASSWORD']:
            if not self.config.get(key):
                _log(f"[ERROR] Missing required parameter: {key}")
                return EXIT_USAGE
        
        if not any([
            self.config.get('DEYE_USERNAME'),
            self.config.get('DEYE_EMAIL'),
            self.config.get('DEYE_MOBILE')
        ]):
            _log("[ERROR] Missing one of: DEYE_USERNAME, DEYE_EMAIL, or DEYE_MOBILE")
            return EXIT_USAGE
        
        if self.config.get('DEYE_MOBILE') and not self.config.get('DEYE_COUNTRY_CODE'):
            _log("[ERROR] DEYE_COUNTRY_CODE required when using DEYE_MOBILE")
            return EXIT_USAGE
        
        # Hash password
        hashed_password = DeyeAPI._sha256(self.config.get('DEYE_PASSWORD'))
        
        # Build request body
        body = {
            'appSecret': self.config.get('DEYE_APP_SECRET'),
            'password': hashed_password,
        }
        
        if self.config.get('DEYE_USERNAME'):
            body['username'] = self.config.get('DEYE_USERNAME')
        if self.config.get('DEYE_EMAIL'):
            body['email'] = self.config.get('DEYE_EMAIL')
        if self.config.get('DEYE_MOBILE'):
            body['mobile'] = self.config.get('DEYE_MOBILE')
            body['countryCode'] = self.config.get('DEYE_COUNTRY_CODE')
        if self.config.get('DEYE_COMPANY_ID'):
            body['companyId'] = int(self.config.get('DEYE_COMPANY_ID'))
        
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/account/token?appId={self.config.get('DEYE_APP_ID')}"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body)
        
        if status_code >= 200 and status_code < 300:
            print(json.dumps(response, indent=2))
            
            # Save token if successful
            if response.get('accessToken'):
                token = response['accessToken']
                self.config.save_config('DEYE_TOKEN', token)
                _log(f"✔ DEYE_TOKEN saved to {self.config.config_file}")
            
            return EXIT_OK
        
        _log(json.dumps(response, indent=2))
        return EXIT_API
    
    def cmd_config_battery(self, args):
        """Read battery configuration"""
        
        device_sn = self.config.get('DEYE_DEVICE_SN')
        
        # Parse positional argument
        if args:
            device_sn = args[0]
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        if not device_sn:
            _log("[ERROR] Missing device serial number")
            return EXIT_USAGE
        
        if not self._validate_device_sn(device_sn):
            return EXIT_USAGE
        
        body = {'deviceSn': device_sn}
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/config/battery"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_config_system(self, args):
        """Read system configuration"""
        
        device_sn = self.config.get('DEYE_DEVICE_SN')
        
        # Parse positional argument
        if args:
            device_sn = args[0]
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        if not device_sn:
            _log("[ERROR] Missing device serial number")
            return EXIT_USAGE
        
        if not self._validate_device_sn(device_sn):
            return EXIT_USAGE
        
        body = {'deviceSn': device_sn}
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/config/system"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_battery_parameter_update(self, args):
        """Update battery parameter"""
        
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--device-sn', default=self.config.get('DEYE_DEVICE_SN'))
        parser.add_argument('--param-type')
        parser.add_argument('--value')
        
        try:
            parsed = parser.parse_args(args)
        except:
            parsed = argparse.Namespace(device_sn=None, param_type=None, value=None)
        
        device_sn = parsed.device_sn or self.config.get('DEYE_DEVICE_SN')
        param_type = parsed.param_type
        value = parsed.value
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        if not device_sn:
            _log("[ERROR] Missing device serial number")
            return EXIT_USAGE
        if not param_type:
            _log("[ERROR] Missing --param-type")
            return EXIT_USAGE
        if not value:
            _log("[ERROR] Missing --value")
            return EXIT_USAGE
        
        valid_types = ['MAX_CHARGE_CURRENT', 'MAX_DISCHARGE_CURRENT', 'GRID_CHARGE_AMPERE', 'BATT_LOW']
        if param_type not in valid_types:
            _log(f"[ERROR] Invalid param-type. Valid: {', '.join(valid_types)}")
            return EXIT_USAGE
        
        if not self._validate_device_sn(device_sn):
            return EXIT_USAGE
        if not self._validate_battery_param(param_type, value):
            return EXIT_USAGE
        
        # Note: Deye API has 'paramterType' typo (single 'e')
        body = {
            'deviceSn': device_sn,
            'paramterType': param_type,
            'value': int(value)
        }
        
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/order/battery/parameter/update"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_station_list(self, args):
        """List all stations"""
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        
        body = {}
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/station/list"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_station_latest(self, args):
        """Get latest station data"""
        
        station_id = self.config.get('DEYE_STATION_ID')
        
        # Parse positional argument
        if args:
            station_id = args[0]
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        if not station_id:
            _log("[ERROR] Missing station ID")
            return EXIT_USAGE
        
        if not self._validate_station_id(station_id):
            return EXIT_USAGE
        
        body = {'stationId': int(station_id)}
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/station/latest"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_device_latest(self, args):
        """Get latest device data"""
        
        device_sn = self.config.get('DEYE_DEVICE_SN')
        
        # Parse positional argument
        if args:
            device_sn = args[0]
        
        if not self.config.get('DEYE_TOKEN'):
            _log("[ERROR] Missing DEYE_TOKEN")
            return EXIT_USAGE
        if not device_sn:
            _log("[ERROR] Missing device serial number")
            return EXIT_USAGE
        
        if not self._validate_device_sn(device_sn):
            return EXIT_USAGE
        
        body = {'deviceList': [device_sn]}
        url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/device/latest"
        
        _log(f"→ POST {url}")
        
        status_code, response = self.api.api_post_json(url, body, self.config.get('DEYE_TOKEN'))
        
        print(json.dumps(response, indent=2))
        return EXIT_OK if status_code >= 200 and status_code < 300 else EXIT_API
    
    def cmd_solar_charge_cron(self, args):
        """Generate solar charge cron file with gradual morning charge modulation.

        Strategy: on sunny days, keep MAX_CHARGE_CURRENT low in the morning
        (gradually ramping up) so the battery doesn't fill before lunch.
        At peak hours (default 12-14) set full charge. After peak, restore default.
        On cloudy days, keep default all day (no modulation).
        """

        # Italian weather code descriptions
        WEATHER_DESCRIPTIONS = {
            0:  "Cielo sereno",
            1:  "Prevalentemente sereno",
            2:  "Parzialmente nuvoloso",
            3:  "Coperto",
            45: "Nebbia",
            48: "Nebbia",
            51: "Pioggia leggera",
            53: "Pioggia moderata",
            55: "Pioggia forte",
            61: "Pioggia leggera",
            63: "Pioggia moderata",
            65: "Pioggia forte",
            71: "Neve leggera",
            73: "Neve moderata",
            75: "Neve forte",
            77: "Granuli di neve",
            80: "Rovesci leggeri",
            81: "Rovesci moderati",
            82: "Rovesci forti",
            85: "Rovesci di neve leggeri",
            86: "Rovesci di neve forti",
            95: "Temporale",
            96: "Temporale con grandine",
            99: "Temporale con grandine forte",
        }

        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('--lat')
        parser.add_argument('--lon')
        parser.add_argument('--hours', default=self.config.get('DEYE_SOLAR_FORECAST_HOURS', '12'))
        parser.add_argument('--min-radiation', default=self.config.get('DEYE_SOLAR_MIN_RADIATION', '200'))
        parser.add_argument('--low-charge-current', default=self.config.get('DEYE_SOLAR_LOW_CHARGE_CURRENT', '5'))
        parser.add_argument('--default-charge-current', default=self.config.get('DEYE_SOLAR_DEFAULT_CHARGE_CURRENT', ''))
        parser.add_argument('--peak-start', default=self.config.get('DEYE_SOLAR_PEAK_START', ''))
        parser.add_argument('--peak-end', default=self.config.get('DEYE_SOLAR_PEAK_END', ''))
        parser.add_argument('--ramp-exponent', default=self.config.get('DEYE_SOLAR_RAMP_EXPONENT', '4'))
        parser.add_argument('--minute', default=self.config.get('DEYE_SOLAR_CRON_MINUTE', '5'))
        parser.add_argument('--cron-file', default=self.config.get('DEYE_SOLAR_CRON_FILE'))
        parser.add_argument('--device-sn', default=self.config.get('DEYE_DEVICE_SN', ''))
        parser.add_argument('--print-slots', action='store_true')
        parser.add_argument('--print-crontab', action='store_true')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--show-config', action='store_true')
        parser.add_argument('--install-crontab', action='store_true')

        try:
            parsed = parser.parse_args(args)
        except:
            return EXIT_USAGE

        latitude = parsed.lat or self.config.get('DEYE_WEATHER_LAT')
        longitude = parsed.lon or self.config.get('DEYE_WEATHER_LON')
        default_charge_current = parsed.default_charge_current or ''

        if not latitude or not longitude:
            _log("[ERROR] Missing --lat and --lon or DEYE_WEATHER_LAT/DEYE_WEATHER_LON")
            return EXIT_USAGE

        if not self._validate_float_range('Latitude', latitude, -90, 90):
            return EXIT_USAGE
        if not self._validate_float_range('Longitude', longitude, -180, 180):
            return EXIT_USAGE

        try:
            forecast_h = int(parsed.hours)
        except:
            _log(f"[ERROR] --hours must be a positive integer, got: '{parsed.hours}'")
            return EXIT_USAGE
        if forecast_h < 1 or forecast_h > 48:
            _log(f"[ERROR] Forecast hours must be 1-48, got: {forecast_h}")
            return EXIT_USAGE

        try:
            cron_min = int(parsed.minute)
        except:
            _log(f"[ERROR] --minute must be 0-59, got: '{parsed.minute}'")
            return EXIT_USAGE
        if cron_min < 0 or cron_min > 59:
            _log(f"[ERROR] Cron minute must be 0-59, got: {cron_min}")
            return EXIT_USAGE

        try:
            low_charge = int(parsed.low_charge_current)
        except:
            _log(f"[ERROR] --low-charge-current must be a positive integer, got: '{parsed.low_charge_current}'")
            return EXIT_USAGE
        if low_charge < 0 or low_charge > 200:
            _log(f"[ERROR] --low-charge-current must be 0-200, got: {low_charge}")
            return EXIT_USAGE

        try:
            ramp_exp = float(parsed.ramp_exponent)
        except:
            _log(f"[ERROR] --ramp-exponent must be a positive number, got: '{parsed.ramp_exponent}'")
            return EXIT_USAGE
        if ramp_exp <= 0:
            _log(f"[ERROR] --ramp-exponent must be > 0, got: {ramp_exp}")
            return EXIT_USAGE
            return EXIT_USAGE

        if parsed.show_config:
            _log("================================================================================")
            _log("              Current solar-charge-cron Configuration")
            _log("================================================================================")
            _log(f"  DEYE_WEATHER_LAT                  = {latitude}")
            _log(f"  DEYE_WEATHER_LON                  = {longitude}")
            _log(f"  DEYE_SOLAR_FORECAST_HOURS         = {parsed.hours} hours")
            _log(f"  DEYE_SOLAR_MIN_RADIATION          = {parsed.min_radiation} W/m²")
            _log(f"  DEYE_SOLAR_LOW_CHARGE_CURRENT     = {parsed.low_charge_current} A")
            _log(f"  DEYE_SOLAR_DEFAULT_CHARGE_CURRENT = {default_charge_current or 'auto-detect'}")
            _log(f"  DEYE_SOLAR_PEAK_START             = {parsed.peak_start or 'auto-detect'}")
            _log(f"  DEYE_SOLAR_PEAK_END               = {parsed.peak_end or 'auto-detect'}")
            _log(f"  DEYE_SOLAR_RAMP_EXPONENT          = {parsed.ramp_exponent}")
            _log(f"  DEYE_SOLAR_CRON_MINUTE            = {parsed.minute}")
            _log(f"  DEYE_SOLAR_CRON_FILE              = {parsed.cron_file}")
            _log(f"  DEYE_DEVICE_SN                    = {parsed.device_sn or 'not set'}")
            _log("================================================================================")

        # Fetch weather forecast
        try:
            import requests as _requests
        except ImportError:
            _log("[ERROR] requests library required for solar-charge-cron")
            return EXIT_DEP

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}"
            f"&hourly=is_day,cloudcover,weathercode,direct_radiation"
            f"&forecast_hours={forecast_h}&timezone=auto"
        )

        _log(f"→ GET {weather_url}")

        connect_timeout = int(self.config.get('DEYE_CONNECT_TIMEOUT', '10'))
        max_time = int(self.config.get('DEYE_MAX_TIME', '30'))
        retry_max = int(self.config.get('DEYE_RETRY_MAX', '2'))
        retry_delay = int(self.config.get('DEYE_RETRY_DELAY', '1'))

        weather_data = None
        for attempt in range(retry_max + 1):
            try:
                resp = _requests.get(weather_url, timeout=(connect_timeout, max_time))
                if resp.status_code >= 500 or resp.status_code == 429:
                    if attempt < retry_max:
                        _log(f"[ERROR] Transient weather API error: HTTP {resp.status_code}. "
                              f"Retry {attempt + 1}/{retry_max} in {retry_delay}s.")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                if resp.status_code != 200:
                    _log(f"[ERROR] Weather API returned HTTP {resp.status_code}")
                    return EXIT_API
                weather_data = resp.json()
                break
            except Exception as e:
                if attempt < retry_max:
                    _log(f"[ERROR] Weather request failed: {e}. Retry {attempt + 1}/{retry_max} in {retry_delay}s.")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                _log(f"[ERROR] Failed to fetch weather forecast: {e}")
                return EXIT_NETWORK

        if weather_data is None:
            _log("[ERROR] Unable to fetch weather forecast.")
            return EXIT_NETWORK

        hourly = weather_data.get('hourly', {})
        times = hourly.get('time', [])
        is_days = hourly.get('is_day', [])
        cloudcovers = hourly.get('cloudcover', [])
        radiations = hourly.get('direct_radiation', [])
        weather_codes = hourly.get('weathercode', [])

        if not times or not radiations:
            _log("[ERROR] Weather API response missing expected hourly fields.")
            return EXIT_API

        # Build slot info
        min_rad = float(parsed.min_radiation)
        slot_data = []

        for i, t in enumerate(times):
            is_day    = is_days[i]      if i < len(is_days)      else 0
            cloudcover = cloudcovers[i] if i < len(cloudcovers)  else 100
            radiation = radiations[i]   if i < len(radiations)   else 0
            code      = weather_codes[i] if i < len(weather_codes) else 99

            # Parse hour from time string
            time_part = t.split('T')[1] if 'T' in t else '00:00'
            hour = int(time_part.split(':')[0])

            # Sunny: daytime + direct radiation above threshold + clear weathercode
            is_sunny = (is_day == 1 and radiation > min_rad and code < 51 and code not in (45, 48))

            slot_data.append({
                'time':        t,
                'hour':        hour,
                'is_day':      is_day,
                'cloudcover':  cloudcover,
                'weathercode': code,
                'description': WEATHER_DESCRIPTIONS.get(code, "Sconosciuto"),
                'radiation':   radiation,
                'sunny':       is_sunny,
            })

        # Determine peak hours from forecast radiation data if not explicitly set
        peak_auto = False
        if not parsed.peak_start and not parsed.peak_end:
            # Auto-detect: find hour with max radiation during daytime
            daytime_slots = [s for s in slot_data if s['is_day'] == 1]
            if daytime_slots:
                max_rad_slot = max(daytime_slots, key=lambda s: s['radiation'])
                peak_hour = max_rad_slot['hour']
                peak_start = peak_hour
                peak_end = peak_hour + 2
                if peak_end > 23:
                    peak_end = 23
                peak_auto = True
                _log(f"ℹ Peak auto-detect: max radiation {max_rad_slot['radiation']:.0f} W/m² at {peak_hour}:00 → peak {peak_start}:00-{peak_end}:00")
            else:
                peak_start = 12
                peak_end = 14
        else:
            try:
                peak_start = int(parsed.peak_start) if parsed.peak_start else 12
            except:
                _log(f"[ERROR] --peak-start must be 0-23, got: '{parsed.peak_start}'")
                return EXIT_USAGE
            if peak_start < 0 or peak_start > 23:
                _log(f"[ERROR] --peak-start must be 0-23, got: {peak_start}")
                return EXIT_USAGE

            try:
                peak_end = int(parsed.peak_end) if parsed.peak_end else 14
            except:
                _log(f"[ERROR] --peak-end must be 0-23, got: '{parsed.peak_end}'")
                return EXIT_USAGE
            if peak_end < 0 or peak_end > 23:
                _log(f"[ERROR] --peak-end must be 0-23, got: {peak_end}")
                return EXIT_USAGE
            if peak_end <= peak_start:
                _log(f"[ERROR] --peak-end ({peak_end}) must be greater than --peak-start ({peak_start})")
                return EXIT_USAGE

        # Determine if this is a "solar day": at least 2 morning hours (before peak)
        # with radiation above threshold
        morning_sunny_count = sum(
            1 for s in slot_data
            if s['sunny'] and s['hour'] < peak_start
        )
        is_solar_day = morning_sunny_count >= 2

        # Auto-detect default charge current from battery config
        if not default_charge_current:
            device_sn = parsed.device_sn
            if not device_sn:
                _log("[ERROR] Cannot auto-detect default MAX_CHARGE_CURRENT without --device-sn or DEYE_DEVICE_SN.")
                _log("[ERROR] Provide --default-charge-current explicitly, or configure DEYE_DEVICE_SN.")
                return EXIT_USAGE
            if not self.config.get('DEYE_TOKEN'):
                _log("[ERROR] Cannot auto-detect default MAX_CHARGE_CURRENT without DEYE_TOKEN.")
                _log("[ERROR] Provide --default-charge-current explicitly, or configure DEYE_TOKEN.")
                return EXIT_USAGE

            battery_url = f"{self.config.get('DEYE_BASE_URL')}/v1.0/config/battery"
            _log(f"→ POST {battery_url} (detect default MAX_CHARGE_CURRENT)")
            status_code, battery_response = self.api.api_post_json(
                battery_url, {'deviceSn': device_sn}, self.config.get('DEYE_TOKEN')
            )
            if status_code < 200 or status_code >= 300:
                _log("[ERROR] Failed to retrieve battery config for auto-detection.")
                return EXIT_API

            detected = (
                battery_response.get('maxChargeCurrent') or
                (battery_response.get('data', {}) or {}).get('maxChargeCurrent')
            )
            if not detected:
                _log("[ERROR] Unable to detect default MAX_CHARGE_CURRENT from config-battery response.")
                return EXIT_API

            default_charge_current = str(detected)
            if not self._validate_battery_param('MAX_CHARGE_CURRENT', default_charge_current):
                return EXIT_API

        default_charge = int(default_charge_current)

        # Compute per-hour charge current for solar days
        # On cloudy days, all hours keep default (no cron entries needed)
        if is_solar_day:
            # Find first sunny hour as modulation start
            modulation_start = peak_start
            for s in slot_data:
                if s.get('sunny') and s['hour'] < peak_start:
                    modulation_start = s['hour']
                    break

            for s in slot_data:
                hour = s['hour']
                if not s['is_day']:
                    s['charge_current'] = default_charge
                elif hour >= modulation_start and hour < peak_start:
                    # Morning before peak: cubic ramp (stays low, rises late)
                    span = peak_start - modulation_start
                    if span > 0:
                        t = (hour - modulation_start) / span  # 0.0 → 1.0
                        time_factor = t ** ramp_exp  # configurable ramp curve
                    else:
                        time_factor = 1.0
                    s['charge_current'] = max(low_charge, min(default_charge, round(
                        low_charge + (default_charge - low_charge) * time_factor
                    )))
                elif hour >= peak_start and hour < peak_end:
                    # Peak hours: full charge
                    s['charge_current'] = default_charge
                else:
                    # After peak or before first sunny hour: default
                    s['charge_current'] = default_charge
        else:
            # Cloudy day: no modulation
            for s in slot_data:
                s['charge_current'] = default_charge

        # Print full table
        if parsed.print_slots:
            headers = [
                'ora_locale', 'is_day', 'cloudcover_pct',
                'weathercode', 'descrizione', 'direct_rad_w/m2', 'sunny_slot',
                'charge_A'
            ]
            rows = []
            for s in slot_data:
                time_str = s['time'].replace('T', ' ')
                rows.append([
                    time_str,
                    str(s['is_day']),
                    str(s['cloudcover']),
                    str(s['weathercode']),
                    s['description'],
                    str(s['radiation']),
                    'SI' if s['sunny'] else 'NO',
                    str(s['charge_current']),
                ])

            col_widths = [len(h) for h in headers]
            for row in rows:
                for j, cell in enumerate(row):
                    col_widths[j] = max(col_widths[j], len(cell))

            fmt = '  '.join(f'{{:<{w}}}' for w in col_widths)
            print(fmt.format(*headers))
            for row in rows:
                print(fmt.format(*row))

        if not is_solar_day:
            _log(f"ℹ Giornata nuvolosa: solo {morning_sunny_count} ore solari mattutine (minimo 2). Nessuna modulazione.")

        # Script path for cron commands (absolute path of the running script)
        script_path = os.path.abspath(__file__)
        config_path = self.config.config_file
        # Generate cron entries: one per hour where charge_current != default
        cron_lines = []
        seen = set()
        modulated_count = 0

        for s in slot_data:
            if s['charge_current'] == default_charge:
                continue

            t = s['time']
            date_part = t.split('T')[0]
            hour = s['hour']

            key = f"{date_part}-{hour}"
            if key in seen:
                continue
            seen.add(key)

            year, month, day = date_part.split('-')
            month_int = int(month)
            day_int   = int(day)

            cron_lines.append(
                f"{cron_min} {hour} {day_int} {month_int} * "
                f'[ "$(date +\\%Y-\\%m-\\%d)" = "{date_part}" ] && '
                f"DEYE_CONFIG='{config_path}' '{script_path}' "
                f"battery-parameter-update --param-type MAX_CHARGE_CURRENT "
                f"--value {s['charge_current']} >>/tmp/deyecli.log 2>&1"
            )
            modulated_count += 1

        # Add restore entry at peak_start to set default charge current
        if is_solar_day and cron_lines:
            # Find the date of the first modulated slot
            first_date = slot_data[0]['time'].split('T')[0]
            for s in slot_data:
                if s['charge_current'] != default_charge:
                    first_date = s['time'].split('T')[0]
                    break
            year, month, day = first_date.split('-')
            month_int = int(month)
            day_int   = int(day)

            restore_key = f"{first_date}-{peak_start}"
            if restore_key not in seen:
                cron_lines.append(
                    f"# Ripristino MAX_CHARGE_CURRENT a {default_charge} A (inizio peak)\n"
                    f"{cron_min} {peak_start} {day_int} {month_int} * "
                    f'[ "$(date +\\%Y-\\%m-\\%d)" = "{first_date}" ] && '
                    f"DEYE_CONFIG='{config_path}' '{script_path}' "
                    f"battery-parameter-update --param-type MAX_CHARGE_CURRENT "
                    f"--value {default_charge} >>/tmp/deyecli.log 2>&1"
                )

        # Build cron file content
        generated_on = datetime.utcnow().isoformat() + 'Z'
        cron_content = (
            f"# deyecli solar-charge-cron generated at {generated_on}\n"
            f"# Location: lat={latitude}, lon={longitude}; forecast_hours={forecast_h}\n"
            f"# Strategy: gradual morning ramp {low_charge}A → {default_charge}A, peak {peak_start}:00-{peak_end}:00\n"
        )
        if not is_solar_day:
            cron_content += f"# Cloudy day: {morning_sunny_count} sunny morning hours (min 2). No modulation.\n"
        cron_content += (
            f"# Install: crontab {parsed.cron_file}\n"
            f"SHELL=/bin/bash\n"
            f"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        )

        if cron_lines:
            for line in cron_lines:
                cron_content += line + "\n"
            _log(f"✔ {modulated_count} ore modulate (mattina), ripristino a {default_charge}A alle {peak_start}:00.")
        else:
            cron_content += f"# Nessuna modulazione necessaria.\n"

        if parsed.dry_run:
            print(cron_content)
            return EXIT_OK

        os.makedirs(os.path.dirname(os.path.abspath(parsed.cron_file)), exist_ok=True)
        with open(parsed.cron_file, 'w') as f:
            f.write(cron_content)
        os.chmod(parsed.cron_file, 0o600)

        _log(f"✔ Cron file generated: {parsed.cron_file}")

        if parsed.print_crontab:
            print(cron_content)

        if parsed.install_crontab:
            ret = os.system(f"crontab '{parsed.cron_file}'")
            if ret == 0:
                _log(f"✔ Crontab installed: crontab {parsed.cron_file}")
            else:
                _log(f"✘ Failed to install crontab (exit code {ret})")
                return EXIT_API
        else:
            _log(f"  Install with: crontab {parsed.cron_file}")

        return EXIT_OK
    
    def cmd_show_config(self, args):
        """Display all configuration parameters"""
        
        config_help = """
================================================================================
                     DEYECLI Configuration Parameters
================================================================================

GLOBAL/AUTHENTICATION PARAMETERS:

  DEYE_BASE_URL
    Default: https://eu1-developer.deyecloud.com
    The Deye Cloud API base URL.

  DEYE_APP_ID, DEYE_APP_SECRET
    Application ID and secret from Deye Cloud developer portal.

  DEYE_EMAIL, DEYE_USERNAME, DEYE_MOBILE, DEYE_COUNTRY_CODE
    Login credentials (at least one required).

  DEYE_PASSWORD
    Plaintext password - will be SHA-256 hashed.

  DEYE_TOKEN
    Bearer token from /token endpoint.

================================================================================

DEVICE/STATION PARAMETERS:

  DEYE_DEVICE_SN
    Device serial number for device operations.

  DEYE_STATION_ID
    Station ID (integer) for station operations.

================================================================================

NETWORK/RETRY PARAMETERS:

  DEYE_CONNECT_TIMEOUT (default: 10)
    Connection timeout in seconds.

  DEYE_MAX_TIME (default: 30)
    Maximum time for requests in seconds.

  DEYE_RETRY_MAX (default: 2)
    Maximum number of retries.

  DEYE_RETRY_DELAY (default: 1)
    Initial retry delay in seconds.

  DEYE_PRINT_QUERY (default: false)
    Print API requests for debugging.

================================================================================

WEATHER/SOLAR PARAMETERS:

  DEYE_WEATHER_LAT, DEYE_WEATHER_LON
    Location for weather forecast (required for solar-charge-cron).

  DEYE_SOLAR_FORECAST_HOURS (default: 12)
    Forecast window in hours.

  DEYE_SOLAR_MIN_RADIATION (default: 200)
    Minimum direct radiation in W/m² for sunny slot.

  DEYE_SOLAR_LOW_CHARGE_CURRENT (default: 5)
    Target charge current when sunny (Amperes).

  DEYE_SOLAR_DEFAULT_CHARGE_CURRENT
    Charge current to restore after sunny slots (auto-detected by default).

  DEYE_SOLAR_CRON_MINUTE (default: 5)
    Cron minute for execution.

  DEYE_SOLAR_CRON_FILE
    Output cron file path.

================================================================================

CONFIGURATION FILE:

  Location: ~/.config/deyecli/config
  Custom: DEYE_CONFIG=/path/to/config

  Format (KEY=VALUE):
    DEYE_APP_ID="your-app-id"
    DEYE_TOKEN="bearer-token-xxx"
    DEYE_WEATHER_LAT="44.0637"
    etc.

  CLI arguments override config file, which override environment variables.

================================================================================
"""
        print(config_help)
        return EXIT_OK


class DeyeAPIServer:
    """HTTP API Server for Deye CLI"""
    
    class RequestHandler(http.server.BaseHTTPRequestHandler):
        cli = None
        
        def do_POST(self):
            self.handle_request()
        
        def do_GET(self):
            self.handle_request()
        
        def handle_request(self):
            try:
                path = urlparse(self.path).path
                query_string = urlparse(self.path).query
                
                # Parse body for POST
                body = {}
                if self.command == 'POST':
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > 0:
                        body = json.loads(self.rfile.read(content_length).decode('utf-8'))
                
                # Parse query string
                query_params = {}
                if query_string:
                    parsed = parse_qs(query_string)
                    query_params = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
                
                # Merge params
                params = {**query_params, **body}
                
                # Extract auth token
                auth_header = self.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    params['token'] = auth_header[7:]
                
                # Route and handle
                response = self.route_api(path, params)
                
                self.send_response(response.get('status', 200))
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
            
            except Exception as e:
                logger.error(f"Error handling request: {e}")
                self.send_error(500, str(e))
        
        def route_api(self, path, params):
            """Route API endpoint"""
            path_lower = path.lower().strip('/')
            
            routes = {
                'api/token': ('token', []),
                'api/config/battery': ('config-battery', ['device_sn']),
                'api/config/system': ('config-system', ['device_sn']),
                'api/battery/parameter/update': ('battery-parameter-update', 
                    ['param_type', 'value', 'device_sn']),
                'api/station/list': ('station-list', []),
                'api/station/latest': ('station-latest', ['station_id']),
                'api/device/latest': ('device-latest', ['device_sn']),
                'api/solar-charge-cron': ('solar-charge-cron', [
                    'lat', 'lon', 'hours', 'min_radiation',
                    'low_charge_current', 'default_charge_current',
                    'peak_start', 'peak_end', 'minute', 'cron_file',
                    'device_sn', 'print_slots', 'dry_run'
                ]),
            }
            
            if path_lower not in routes:
                return {
                    'status': 404,
                    'error': f'Endpoint not found: {path}',
                    'available_endpoints': list(routes.keys())
                }
            
            cmd, param_names = routes[path_lower]
            
            try:
                return self.execute_cmd(cmd, params, param_names)
            except Exception as e:
                logger.error(f"Error executing command {cmd}: {e}")
                return {
                    'status': 500,
                    'error': f'Error executing command: {str(e)}',
                    'command': cmd
                }
        
        def execute_cmd(self, cmd, params, param_names):
            """Execute CLI command via API"""
            
            # Set configuration from params
            for param_name in param_names:
                if param_name in params:
                    key = param_name.upper()
                    if not key.startswith('DEYE_'):
                        key = 'DEYE_' + key
                    self.cli.config.config[key] = str(params[param_name])
            
            if 'token' in params:
                self.cli.config.config['DEYE_TOKEN'] = params['token']
            if 'base_url' in params:
                self.cli.config.config['DEYE_BASE_URL'] = params['base_url']
            
            # Execute command
            args = []
            for param_name in param_names:
                if param_name in params:
                    value = params[param_name]
                    if isinstance(value, bool) or param_name.endswith('_slots') or param_name.endswith('_run'):
                        if value and str(value).lower() in ('true', '1', 'yes', 'on'):
                            args.append(f'--{param_name.replace("_", "-")}')
                    else:
                        args.append(str(value))
            
            # Call CLI command
            method = getattr(self.cli, f'cmd_{cmd.replace("-", "_")}', None)
            if method:
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                try:
                    # Capture output
                    from io import StringIO
                    sys.stdout = StringIO()
                    sys.stderr = StringIO()
                    
                    exit_code = method(args)
                    
                    output = sys.stdout.getvalue()
                    error_output = sys.stderr.getvalue()
                    
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
                    
                    try:
                        data = json.loads(output) if output else {}
                    except:
                        data = {'raw_output': output}
                    
                    return {
                        'status': 200 if exit_code == EXIT_OK else 400,
                        'success': exit_code == EXIT_OK,
                        'command': cmd,
                        'data': data,
                        'error': error_output if error_output else None
                    }
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
            
            return {
                'status': 404,
                'error': f'Command not found: {cmd}'
            }
        
        def log_message(self, format, *args):
            """Override to use custom logger"""
            logger.info(f"{self.client_address[0]} - {format % args}")
    
    def __init__(self, cli: DeyCLI, host: str = '0.0.0.0', port: int = 8000):
        self.cli = cli
        self.host = host
        self.port = port
        self.RequestHandler.cli = cli
    
    def start(self):
        """Start the API server"""
        try:
            with socketserver.TCPServer((self.host, self.port), self.RequestHandler) as httpd:
                logger.info(f"Starting Deye API Server on {self.host}:{self.port}")
                logger.info(f"API endpoints:")
                logger.info(f"  POST /api/token")
                logger.info(f"  GET  /api/station/list")
                logger.info(f"  GET  /api/station/latest")
                logger.info(f"  GET  /api/device/latest")
                logger.info(f"  GET  /api/config/battery")
                logger.info(f"  GET  /api/config/system")
                logger.info(f"  POST /api/battery/parameter/update")
                logger.info(f"  POST /api/solar-charge-cron")
                logger.info(f"Press Ctrl+C to stop")
                httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Server error: {e}")
            sys.exit(1)


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description='Deye CLI - Deye Cloud API CLI and HTTP API Server',
        epilog='''
Solar Charge Cron - Funzionamento:
  Il comando solar-charge-cron analizza le previsioni meteo (Open-Meteo) e
  genera un crontab che modula MAX_CHARGE_CURRENT ora per ora durante la
  mattina, in modo che la batteria si carichi lentamente e l'energia in
  eccesso venga esportata verso la rete.

  La rampa mattutina segue una curva esponenziale: charge = low + (max - low) * t^exp
  dove t va da 0 (prima ora soleggiata) a 1 (inizio peak).

  --ramp-exponent controlla la forma della curva:
    1   = lineare (sale uniformemente)
    2   = quadratica (sale piano, poi accelera)
    4   = quartica (resta bassa a lungo, sale tardi) [default]
    6+  = molto piatta (quasi tutto al minimo, impennata finale)

  Il peak (ore di carica piena) viene auto-rilevato dall'ora con massima
  radiazione solare prevista. Puo' essere forzato con --peak-start/--peak-end.

Examples:
  # Obtain a token
  deyecli.py token --app-id xxx --app-secret yyy --email me@example.com --password mypass

  # Read battery config
  deyecli.py config-battery DEVICE_SN

  # List stations
  deyecli.py station-list

  # Generate solar charge cron (dry-run con stampa slot)
  deyecli.py solar-charge-cron --print-slots --dry-run

  # Generate e installa crontab con curva piatta
  deyecli.py solar-charge-cron --ramp-exponent 6 --install-crontab

  # Start API server
  deyecli.py api --host 0.0.0.0 --port 8000
        '''
    ,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Global options
    parser.add_argument('--base-url', default=None, help='API base URL')
    parser.add_argument('--app-id', default=None, help='Application ID')
    parser.add_argument('--app-secret', default=None, help='Application secret')
    parser.add_argument('--username', default=None, help='Username')
    parser.add_argument('--email', default=None, help='Email')
    parser.add_argument('--mobile', default=None, help='Mobile number')
    parser.add_argument('--country-code', default=None, help='Country code')
    parser.add_argument('--password', default=None, help='Password')
    parser.add_argument('--company-id', default=None, help='Company ID')
    parser.add_argument('--token', default=None, help='Bearer token')
    parser.add_argument('--device-sn', default=None, help='Device serial number')
    parser.add_argument('--station-id', default=None, help='Station ID')
    parser.add_argument('--print-query', action='store_true', help='Print API queries')
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Token command
    token_parser = subparsers.add_parser('token', help='Obtain access token')
    
    # Config commands
    subparsers.add_parser('config-battery', help='Read battery configuration')
    subparsers.add_parser('config-system', help='Read system configuration')
    
    # Battery parameter update
    battery_parser = subparsers.add_parser('battery-parameter-update', help='Update battery parameter')
    battery_parser.add_argument('--param-type', required=True, help='Parameter type')
    battery_parser.add_argument('--value', required=True, type=int, help='Parameter value')
    
    # Station commands
    subparsers.add_parser('station-list', help='List stations')
    subparsers.add_parser('station-latest', help='Get latest station data')
    
    # Device commands
    subparsers.add_parser('device-latest', help='Get latest device data')
    
    # Solar charge cron
    solar_parser = subparsers.add_parser('solar-charge-cron',
        help='Generate solar charge cron',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Funzionamento:
  Analizza le previsioni meteo (Open-Meteo) e genera un crontab che modula
  MAX_CHARGE_CURRENT ora per ora durante la mattina, in modo che la batteria
  si carichi lentamente e l'energia in eccesso venga esportata verso la rete.

  La rampa mattutina segue una curva esponenziale: charge = low + (max - low) * t^exp
  dove t va da 0 (prima ora soleggiata) a 1 (inizio peak).

  --ramp-exponent controlla la forma della curva:
    1   = lineare (sale uniformemente)
    2   = quadratica (sale piano, poi accelera)
    4   = quartica (resta bassa a lungo, sale tardi) [default]
    6+  = molto piatta (quasi tutto al minimo, impennata finale)

  Il peak (ore di carica piena) viene auto-rilevato dall'ora con massima
  radiazione solare prevista. Puo' essere forzato con --peak-start/--peak-end.

Esempio:
  deyecli.py solar-charge-cron --ramp-exponent 2 --print-slots --dry-run
  deyecli.py solar-charge-cron --ramp-exponent 6 --install-crontab
''')
    solar_parser.add_argument('--lat', help='Latitude')
    solar_parser.add_argument('--lon', help='Longitude')
    solar_parser.add_argument('--hours', type=int, help='Forecast hours')
    solar_parser.add_argument('--min-radiation', type=int, help='Min radiation W/m²')
    solar_parser.add_argument('--low-charge-current', type=int, help='Low charge current A')
    solar_parser.add_argument('--default-charge-current', type=int, help='Default charge current A (auto-detect if omitted)')
    solar_parser.add_argument('--peak-start', type=int, help='Peak charge start hour (auto-detect from max radiation if omitted)')
    solar_parser.add_argument('--peak-end', type=int, help='Peak charge end hour (auto-detect if omitted)')
    solar_parser.add_argument('--ramp-exponent', type=float, help='Ramp curve exponent (1=linear, 4=default, 6+=very flat)')
    solar_parser.add_argument('--minute', type=int, help='Cron minute')
    solar_parser.add_argument('--cron-file', help='Cron file path')
    solar_parser.add_argument('--print-slots', action='store_true')
    solar_parser.add_argument('--print-crontab', action='store_true', help='Print generated crontab content')
    solar_parser.add_argument('--dry-run', action='store_true')
    solar_parser.add_argument('--show-config', action='store_true')
    solar_parser.add_argument('--install-crontab', action='store_true', help='Install crontab in the system after generating')
    
    # API server command
    api_parser = subparsers.add_parser('api', help='Start HTTP API server')
    api_parser.add_argument('--host', default='0.0.0.0', help='Bind address')
    api_parser.add_argument('--port', type=int, default=8000, help='Listen port')
    
    # Show config
    subparsers.add_parser('show-config', help='Show configuration')
    
    args = parser.parse_args()
    
    # Initialize config
    config = DeyeConfig()
    
    # Apply command-line arguments
    if args.base_url:
        config.config['DEYE_BASE_URL'] = args.base_url
    if args.app_id:
        config.config['DEYE_APP_ID'] = args.app_id
    if args.app_secret:
        config.config['DEYE_APP_SECRET'] = args.app_secret
    if args.username:
        config.config['DEYE_USERNAME'] = args.username
    if args.email:
        config.config['DEYE_EMAIL'] = args.email
    if args.mobile:
        config.config['DEYE_MOBILE'] = args.mobile
    if args.country_code:
        config.config['DEYE_COUNTRY_CODE'] = args.country_code
    if args.password:
        config.config['DEYE_PASSWORD'] = args.password
    if args.company_id:
        config.config['DEYE_COMPANY_ID'] = args.company_id
    if args.token:
        config.config['DEYE_TOKEN'] = args.token
    if args.device_sn:
        config.config['DEYE_DEVICE_SN'] = args.device_sn
    if args.station_id:
        config.config['DEYE_STATION_ID'] = args.station_id
    if args.print_query:
        config.config['DEYE_PRINT_QUERY'] = 'true'
    
    # Initialize CLI
    cli = DeyCLI(config)
    
    # Execute command
    if not args.command:
        parser.print_help()
        return EXIT_OK
    
    if args.command == 'token':
        return cli.cmd_token([])
    elif args.command == 'show-config':
        return cli.cmd_show_config([])
    elif args.command == 'config-battery':
        return cli.cmd_config_battery([])
    elif args.command == 'config-system':
        return cli.cmd_config_system([])
    elif args.command == 'battery-parameter-update':
        cmd_args = [
            '--param-type', args.param_type,
            '--value', str(args.value)
        ]
        return cli.cmd_battery_parameter_update(cmd_args)
    elif args.command == 'station-list':
        return cli.cmd_station_list([])
    elif args.command == 'station-latest':
        return cli.cmd_station_latest([])
    elif args.command == 'device-latest':
        return cli.cmd_device_latest([])
    elif args.command == 'solar-charge-cron':
        cmd_args = []
        if args.lat:
            cmd_args.extend(['--lat', str(args.lat)])
        if args.lon:
            cmd_args.extend(['--lon', str(args.lon)])
        if args.hours:
            cmd_args.extend(['--hours', str(args.hours)])
        if args.min_radiation:
            cmd_args.extend(['--min-radiation', str(args.min_radiation)])
        if args.low_charge_current:
            cmd_args.extend(['--low-charge-current', str(args.low_charge_current)])
        if args.default_charge_current:
            cmd_args.extend(['--default-charge-current', str(args.default_charge_current)])
        if args.peak_start:
            cmd_args.extend(['--peak-start', str(args.peak_start)])
        if args.peak_end:
            cmd_args.extend(['--peak-end', str(args.peak_end)])
        if args.ramp_exponent:
            cmd_args.extend(['--ramp-exponent', str(args.ramp_exponent)])
        if args.minute:
            cmd_args.extend(['--minute', str(args.minute)])
        if args.cron_file:
            cmd_args.extend(['--cron-file', args.cron_file])
        if args.print_slots:
            cmd_args.append('--print-slots')
        if args.print_crontab:
            cmd_args.append('--print-crontab')
        if args.dry_run:
            cmd_args.append('--dry-run')
        if args.show_config:
            cmd_args.append('--show-config')
        if args.install_crontab:
            cmd_args.append('--install-crontab')
        return cli.cmd_solar_charge_cron(cmd_args)
    elif args.command == 'api':
        server = DeyeAPIServer(cli, args.host, args.port)
        server.start()
        return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
