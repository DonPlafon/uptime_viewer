import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]


class HttpSmokeTests(unittest.TestCase):
    def test_real_sanic_startup_routes_and_monitor(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'http_smoke_app.py'), str(port)],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        opener = build_opener(ProxyHandler({}))

        def fetch(path):
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                return response.read()

        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail('Sanic fixture failed: ' + process.communicate(timeout=2)[0])
                try:
                    self.assertEqual(json.loads(fetch('/health')), {'status': 'ok'})
                    break
                except URLError:
                    time.sleep(0.1)
            else:
                self.fail('Sanic fixture did not become healthy within 15 seconds')
            self.assertIn(b'Service Status', fetch('/'))
            self.assertIn(b'import {duration', fetch('/js/main.js'))
            self.assertIn(b'export function', fetch('/js/metrics.mjs'))
            services = json.loads(fetch('/api/services'))
            self.assertEqual(services[0]['url'], 'https://example.com/')
            status = json.loads(fetch('/api/status/1?hours=invalid'))
            self.assertEqual(status['period_hours'], 24)
            self.assertIn('now', status)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
