#!/usr/bin/env python3
"""
Deye CLI HTTP API Server
Exposes deyecli.sh commands as REST endpoints for remote integration (e.g., Home Assistant)
"""

import http.server
import socketserver
import json
import subprocess
import os
import sys
import logging
import argparse
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DeyeAPIHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for Deye API endpoints"""
    
    # Store the CLI script path and config
    cli_script = None
    env_vars = {}
    
    def do_POST(self):
        """Handle POST requests"""
        self.handle_request()
    
    def do_GET(self):
        """Handle GET requests (allow GET for query endpoints)"""
        self.handle_request()
    
    def handle_request(self):
        """Route and execute API command"""
        try:
            path = urlparse(self.path).path
            query_string = urlparse(self.path).query
            
            # Parse request body for POST requests
            body = {}
            if self.command == 'POST':
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            # Parse query string for GET requests
            query_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(query_string).items()}
            
            # Merge query params and body
            params = {**query_params, **body}
            
            # Extract authorization header
            auth_header = self.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                params['token'] = auth_header[7:]
            
            # Route to appropriate handler
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
        """Route API path to appropriate command"""
        path_lower = path.lower().strip('/')
        
        routes = {
            'api/token': ('token', []),
            'api/config/battery': ('config-battery', ['device_sn']),
            'api/config/system': ('config-system', ['device_sn']),
            'api/battery/parameter/update': ('battery-parameter-update', ['param_type', 'value', 'device_sn']),
            'api/station/list': ('station-list', []),
            'api/station/latest': ('station-latest', ['station_id']),
            'api/device/latest': ('device-latest', ['device_sn']),
            'api/solar-charge-cron': ('solar-charge-cron', [
                'lat', 'lon', 'hours', 'cloud_max', 'min_radiation',
                'low_charge_current', 'restore_default_charge_current',
                'default_charge_current', 'minute', 'cron_file', 'device_sn', 
                'print_slots', 'dry_run'
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
            result = self.execute_cmd(cmd, params, param_names)
            return result
        except Exception as e:
            logger.error(f"Error executing command {cmd}: {e}")
            return {
                'status': 500,
                'error': f'Error executing command: {str(e)}',
                'command': cmd
            }
    
    def execute_cmd(self, cmd, params, param_names):
        """Execute a deyecli command and return formatted response"""
        
        # Build argument list
        args = [self.cli_script, cmd]
        
        # Add global parameters
        if 'token' in params:
            args.extend(['--token', params['token']])
        if 'base_url' in params:
            args.extend(['--base-url', params['base_url']])
        
        # Add command-specific parameters (convert underscores to hyphens)
        for param_name in param_names:
            if param_name in params:
                value = params[param_name]
                # Handle boolean flags
                if param_name.endswith('_default_charge_current') or param_name.endswith('_slots') or param_name.endswith('_run'):
                    if value and str(value).lower() in ('true', '1', 'yes', 'on'):
                        args.append(f'--{param_name.replace("_", "-")}')
                else:
                    args.append(f'--{param_name.replace("_", "-")}')
                    if not (param_name.endswith('_default_charge_current') or param_name.endswith('_slots') or param_name.endswith('_run')):
                        args.append(str(value))
        
        # Prepare environment
        env = os.environ.copy()
        env.update(self.env_vars)
        
        logger.info(f"Executing: {' '.join(args)}")
        
        # Execute command
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )
        
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            output = {'raw_output': result.stdout}
        
        if result.returncode == 0:
            return {
                'status': 200,
                'success': True,
                'command': cmd,
                'data': output
            }
        else:
            return {
                'status': 400 if result.returncode < 100 else 500,
                'success': False,
                'command': cmd,
                'error': result.stderr or 'Command failed',
                'exit_code': result.returncode
            }
    
    def log_message(self, format, *args):
        """Override to use custom logger"""
        logger.info(f"{self.client_address[0]} - {format % args}")


def load_config():
    """Load environment variables from config file"""
    env_vars = os.environ.copy()
    
    # Try to load from config file
    config_file = os.getenv('DEYE_CONFIG')
    if not config_file:
        config_file = os.path.expanduser('~/.config/deyecli/config')
    
    if os.path.exists(config_file):
        logger.info(f"Loading config from {config_file}")
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"\'')
                        if key.startswith('DEYE_'):
                            env_vars[key] = value
        except Exception as e:
            logger.warning(f"Error loading config file: {e}")
    
    return env_vars


def main():
    parser = argparse.ArgumentParser(
        description='Deye CLI HTTP API Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Start API server on localhost:8000
  python3 api_server.py --host 0.0.0.0 --port 8000

  # With custom CLI script location
  python3 api_server.py --cli ./deyecli.sh --port 9000

  # Test with curl:
  curl -X POST http://localhost:8000/api/token -H "Content-Type: application/json" \\
    -d '{"app_id":"xxx","app_secret":"yyy","email":"me@example.com","password":"pass"}'
        '''
    )
    
    parser.add_argument('--host', default='0.0.0.0', help='Bind address (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000, help='Listen port (default: 8000)')
    parser.add_argument('--cli', default='./deyecli.sh', help='Path to deyecli.sh script')
    
    args = parser.parse_args()
    
    # Verify CLI script exists
    if not os.path.exists(args.cli):
        logger.error(f"CLI script not found: {args.cli}")
        sys.exit(1)
    
    # Make it executable
    os.chmod(args.cli, 0o755)
    
    # Load env vars from config
    env_vars = load_config()
    DeyeAPIHandler.cli_script = args.cli
    DeyeAPIHandler.env_vars = env_vars
    
    # Create and start server
    handler = DeyeAPIHandler
    
    try:
        with socketserver.TCPServer((args.host, args.port), handler) as httpd:
            logger.info(f"Starting Deye API Server on {args.host}:{args.port}")
            logger.info(f"Using CLI script: {args.cli}")
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


if __name__ == '__main__':
    main()
