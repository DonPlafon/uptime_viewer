"""Bounded browser preview of real frontend with synthetic API data; no database needed."""
import argparse
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).replace(microsecond=0)
SERVICES = [
    {'id': 1, 'name': 'Main website', 'url': 'https://www.example.com'},
    {'id': 2, 'name': 'Public API', 'url': 'https://api.example.com'},
    {'id': 3, 'name': 'Background jobs', 'url': 'https://jobs.example.com'},
]


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def status(service_id, hours):
    cutoff = NOW - timedelta(hours=hours)
    outages = {
        1: [(18120, 18100), (5300, 5290)],
        2: [(28800, 28620), (18200, 17200), (8600, 8450), (420, 0)],
        3: [],
    }[service_id]
    logs = []
    start = cutoff
    for start_ago, end_ago in outages:
        down_start, down_end = NOW - timedelta(seconds=start_ago), NOW - timedelta(seconds=end_ago)
        if down_end < cutoff:
            continue
        if down_start > start:
            logs.append({'state': 'UP', 'start_time': iso(start), 'end_time': iso(down_start)})
        logs.append({'state': 'DOWN', 'start_time': iso(down_start), 'end_time': iso(down_end) if end_ago else None})
        start = down_end
    if start < NOW:
        logs.append({'state': 'UP', 'start_time': iso(start), 'end_time': None})
    return {'logs': logs, 'period_hours': hours, 'now': iso(NOW), 'cutoff': iso(cutoff), 'check_interval_seconds': 10}


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript'}

    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        if not parsed.path.startswith('/api/'):
            return super().do_GET()
        hours = max(1, min(int(parse_qs(parsed.query).get('hours', ['24'])[0]), 720))
        if parsed.path == '/api/services':
            result = SERVICES
        else:
            service_id = int(parsed.path.rsplit('/', 1)[1])
            if parsed.path.startswith('/api/status/'):
                result = status(service_id, hours)
            else:
                result = {'pings': [
                    {'time': iso(NOW - timedelta(hours=hours * (23 - i) / 24)),
                     'ping_ms': 72 + service_id * 32 + (i * 17 % 65) + (560 if service_id == 2 and i in (7, 15, 23) else 0), 'samples': 60}
                    for i in range(24)
                ]}
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--renderer', help='Optional extra CDP screenshot renderer')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'frontend')))
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f'http://127.0.0.1:{server.server_port}'
    out = ROOT / '.artifacts' / 'preview'
    out.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'browser_check.py'), url, str(out)], timeout=120, check=True)
        if args.renderer:
            subprocess.run([sys.executable, args.renderer, '--url', url, '--out', str(out), '--name', 'uptime-preview',
                            '--wait-ms', '2500', '--viewports', 'desktop=1440x1200,tablet=820x1180,mobile=390x1400'], timeout=150, check=True)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == '__main__':
    main()
