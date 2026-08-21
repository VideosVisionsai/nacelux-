import json, os, sqlite3, sys, tempfile, unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import urlopen, Request
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import app
import database

class HealthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.server = HTTPServer(('127.0.0.1', 0), app.API)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_health_readiness_endpoint(self):
        req = Request(f"http://127.0.0.1:{self.port}/api/v1/health")
        with urlopen(req, timeout=5) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertEqual(data.get('status'), 'HEALTHY')
            self.assertEqual(data.get('version'), '2.1')
            self.assertIn('database', data)
            self.assertIn('storage', data)
            self.assertIn('ocr', data)
            self.assertIn('resa_connector', data)

    def test_root_liveness_endpoint(self):
        req = Request(f"http://127.0.0.1:{self.port}/health")
        with urlopen(req, timeout=5) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertEqual(data.get('status'), 'ALIVE')

    def test_explicit_liveness_and_readiness_subpaths(self):
        req_live = Request(f"http://127.0.0.1:{self.port}/health/liveness")
        with urlopen(req_live, timeout=5) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertEqual(data.get('status'), 'ALIVE')

        req_ready = Request(f"http://127.0.0.1:{self.port}/health/readiness")
        with urlopen(req_ready, timeout=5) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertEqual(data.get('status'), 'HEALTHY')

if __name__ == '__main__':
    unittest.main()
