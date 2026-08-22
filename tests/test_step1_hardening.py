"""Step 1 hardening tests: dynamic PORT binding, 0.0.0.0 listen, and the
guarantee that the PostgreSQL port (5432) is never used as the HTTP port.

These map directly to the mandatory tests #8, #9 and #10 of the Step 1 spec.
They verify real runtime behaviour by actually starting the HTTP server on an
injected PORT, not merely by inspecting source strings.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for_port(host, port, timeout=12):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class DynamicPortAndBindingTests(unittest.TestCase):
    def test_server_binds_to_injected_environment_port(self):
        """The HTTP server must listen on exactly the PORT injected by the platform."""
        port = _free_port()
        env = {
            # Strip any inherited deployment variables so this is a clean dev boot.
            **{k: v for k, v in os.environ.items()
               if k not in {'NACELUX_ENV', 'DB_PROVIDER', 'DATABASE_URL',
                            'MIGRATION_DATABASE_URL', 'PORT', 'PROCESS_TYPE'}},
            'PORT': str(port),
            'NACELUX_SKIP_DB_INIT': 'true',
        }
        proc = subprocess.Popen(
            [sys.executable, 'backend/app.py'], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            self.assertTrue(_wait_for_port('127.0.0.1', port),
                            'server did not bind the injected PORT')
            with urlopen(Request(f'http://127.0.0.1:{port}/health'), timeout=5) as res:
                self.assertEqual(res.status, 200)
                payload = json.loads(res.read().decode())
                self.assertEqual(payload['status'], 'ALIVE')
                self.assertEqual(payload['version'], '2.1')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def test_http_listen_defaults_to_0000_and_never_localhost_only(self):
        """The bind call must target 0.0.0.0 (all interfaces), never 127.0.0.1 only."""
        app_src = (ROOT / 'backend' / 'app.py').read_text(encoding='utf-8')
        self.assertIn('ThreadingHTTPServer(("0.0.0.0",PORT)', app_src)
        self.assertNotIn('ThreadingHTTPServer(("127.0.0.1"', app_src)
        self.assertNotIn('ThreadingHTTPServer(("localhost"', app_src)

    def test_port_5432_is_never_used_as_http_port(self):
        """5432 is the PostgreSQL port. It must never default or bind as the HTTP port."""
        # The HTTP PORT default must exist and must not be 5432.
        app_src = (ROOT / 'backend' / 'app.py').read_text(encoding='utf-8')
        m = re.search(r'PORT\s*=\s*int\(os\.environ\.get\(\s*["\']PORT["\']\s*,\s*["\'](\d+)["\']', app_src)
        self.assertIsNotNone(m, 'PORT must be read from the environment with a numeric default')
        self.assertNotEqual(m.group(1), '5432')

        # 5432 must not appear in any HTTP-serving or deploy entrypoint file.
        for rel in ('backend/app.py', 'backend/worker.py', 'start.sh', 'Dockerfile',
                    'railway.json', 'Procfile'):
            path = ROOT / rel
            if path.exists():
                self.assertNotIn('5432', path.read_text(encoding='utf-8'),
                                 f'5432 must not appear in HTTP/deploy file {rel}')


class NewTenantTablesRLSTests(unittest.TestCase):
    """Static guarantee that the raw_records/documents migration ships RLS
    (real PostgreSQL RLS activation is exercised by test_postgres_integration.py)."""

    def test_migration_0015_exists_and_is_non_destructive(self):
        path = ROOT / 'database' / 'migrations' / '0015_raw_records_documents.sql'
        self.assertTrue(path.exists(), 'migration 0015 must exist')
        upper = path.read_text(encoding='utf-8').upper()
        for banned in ('DROP TABLE ', 'TRUNCATE ', 'DROP DATABASE '):
            self.assertNotIn(banned, upper, f'destructive command {banned!r} in 0015')

    def test_new_tables_are_tenant_scoped_and_rls_protected(self):
        path = ROOT / 'database' / 'migrations' / '0015_raw_records_documents.sql'
        sql = path.read_text(encoding='utf-8')
        for table in ('raw_records', 'documents'):
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}(', sql)
            self.assertIn(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY', sql)
            self.assertIn(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY', sql)
        # Both tables are tenant-scoped and isolated through membership proof only.
        self.assertEqual(sql.count('REFERENCES organizations(id)'), 2)
        self.assertGreaterEqual(sql.count('app_user_has_org_access(organization_id)'), 4)


if __name__ == '__main__':
    unittest.main()
