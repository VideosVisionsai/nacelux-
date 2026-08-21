import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_import(extra):
    env = {k: v for k, v in os.environ.items() if k not in {
        'NACELUX_ENV', 'DB_PROVIDER', 'DATABASE_URL', 'DB_SSLMODE', 'SUPABASE_URL',
        'SUPABASE_ANON_KEY', 'AUTH_COOKIE_SECURE', 'AUTH_REDIRECT_URL',
        'DOCUMENT_STORAGE_PROVIDER', 'SUPABASE_SERVICE_ROLE_KEY',
        'SUPABASE_STORAGE_BUCKET', 'AUTO_MIGRATE', 'MIGRATE_SQLITE_DATA',
    }}
    env.update(extra)
    return subprocess.run(
        [sys.executable, '-c', 'import sys; sys.path.insert(0, "backend"); import db_adapter'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )


class ProductionGuardTests(unittest.TestCase):
    def test_production_without_database_fails_closed(self):
        result = run_import({'NACELUX_ENV': 'production', 'DB_PROVIDER': 'postgresql'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DATABASE_URL', result.stderr)
        self.assertNotIn('password', result.stderr.lower())

    def test_production_sqlite_provider_fails_closed(self):
        result = run_import({
            'NACELUX_ENV': 'production',
            'DB_PROVIDER': 'sqlite',
            'DATABASE_URL': 'postgresql://runtime:secret@db.example.test:5432/postgres?sslmode=require',
            'DB_SSLMODE': 'require',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('DB_PROVIDER=postgresql', result.stderr)
        self.assertNotIn('secret', result.stderr)

    def test_production_without_supabase_auth_fails_closed(self):
        result = subprocess.run(
            [sys.executable, '-c', 'import sys; sys.path.insert(0, "backend"); import auth'],
            cwd=ROOT,
            env={**os.environ, 'NACELUX_ENV': 'production', 'DB_PROVIDER': 'postgresql',
                 'DATABASE_URL': 'postgresql://runtime:secret@db.example.test:5432/postgres?sslmode=require',
                 'DB_SSLMODE': 'require'},
            capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue('Supabase Auth' in result.stderr or 'SUPABASE_URL' in result.stderr)
        self.assertNotIn('secret', result.stderr)

    def test_production_postgresql_adapter_never_selects_sqlite(self):
        result = subprocess.run(
            [sys.executable, '-c', 'import sys; sys.path.insert(0, "backend"); import db_adapter; assert db_adapter.IS_POSTGRES; assert db_adapter.BACKEND == "postgresql"'],
            cwd=ROOT,
            env={**os.environ, 'NACELUX_ENV': 'production', 'DB_PROVIDER': 'postgresql',
                 'DATABASE_URL': 'postgresql://runtime:secret@db.example.test:5432/postgres?sslmode=require',
                 'DB_SSLMODE': 'require'},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_session_requires_authentication_and_is_not_demo(self):
        script = r'''
import sys, threading
from http.server import HTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
sys.path.insert(0, 'backend')
import app
server = HTTPServer(('127.0.0.1', 0), app.API)
threading.Thread(target=server.handle_request, daemon=True).start()
try:
    urlopen('http://127.0.0.1:%d/api/v1/session' % server.server_port, timeout=3)
    raise AssertionError('unauthenticated production session unexpectedly succeeded')
except HTTPError as exc:
    body = exc.read().decode()
    assert exc.code == 401, (exc.code, body)
    assert 'DEMO' not in body
finally:
    server.server_close()
'''
        env = {**os.environ, 'NACELUX_ENV': 'production', 'DB_PROVIDER': 'postgresql',
               'DATABASE_URL': 'postgresql://runtime:secret@db.example.test:5432/postgres?sslmode=require',
               'DB_SSLMODE': 'require',
               'SUPABASE_URL': 'https://project.supabase.co', 'SUPABASE_ANON_KEY': 'anon-live-key',
               'AUTH_COOKIE_SECURE': 'true', 'AUTH_REDIRECT_URL': 'https://app.nacelux.test',
               'DOCUMENT_STORAGE_PROVIDER': 'supabase', 'SUPABASE_SERVICE_ROLE_KEY': 'service-live-key',
               'SUPABASE_STORAGE_BUCKET': 'resa-documents'}
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_frontend_has_no_demo_labels_or_service_role_key(self):
        frontend = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'frontend').glob('*'))
        self.assertNotRegex(frontend, r'(?i)demo|sqlite|service.?role|database_url|jwt')

    def test_diagnostics_redact_database_urls_and_jwts(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        from db_adapter import redact_error
        value = redact_error('postgresql://u:super-secret@db.invalid/postgres Bearer eyJheader.payload.signature')
        self.assertNotIn('super-secret', value)
        self.assertNotIn('eyJheader.payload.signature', value)
        self.assertNotIn('Bearer eyJheader.payload.signature', value)


if __name__ == '__main__':
    unittest.main()
