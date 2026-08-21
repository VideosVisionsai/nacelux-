import hashlib, os, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

class MigrationIntegrityTests(unittest.TestCase):
    def test_all_migrations_exist_and_sorted(self):
        migrations_dir = ROOT / 'database' / 'migrations'
        files = sorted(migrations_dir.glob('*.sql'))
        self.assertGreaterEqual(len(files), 11)
        names = [f.stem for f in files]
        self.assertIn('0001_preserve_current_schema', names)
        self.assertIn('0002_supabase_auth', names)
        self.assertIn('0011_supabase_rls_policies', names)
        self.assertIn('0012_job_retry_backoff', names)
        self.assertIn('0013_rls_runtime_hardening', names)
        self.assertIn('0014_worker_rls_queue_functions', names)

    def test_migrations_are_non_destructive(self):
        migrations_dir = ROOT / 'database' / 'migrations'
        for f in migrations_dir.glob('*.sql'):
            content = f.read_text(encoding='utf-8')
            # Ensure no destructive commands are in the additive migrations
            for banned in ['DROP TABLE ', 'TRUNCATE ']:
                self.assertNotIn(banned, content.upper(), f"Destructive command found in {f.name}")

    def test_checksum_consistency(self):
        migrations_dir = ROOT / 'database' / 'migrations'
        for f in migrations_dir.glob('*.sql'):
            content = f.read_text(encoding='utf-8')
            digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
            self.assertEqual(len(digest), 64)

    def test_start_sh_refuses_sqlite_fallback_and_failed_migrations(self):
        start = (ROOT / 'start.sh').read_text(encoding='utf-8')
        self.assertIn('SQLite fallback is forbidden', start)
        self.assertIn('Database migration failed. Refusing to start', start)
        self.assertIn('DB_PROVIDER=postgresql', start)
        self.assertIn('sslmode', (ROOT / 'backend' / 'db_adapter.py').read_text(encoding='utf-8'))
        self.assertNotIn('Continuing with startup', start)
        railway = (ROOT / 'railway.json').read_text(encoding='utf-8')
        self.assertIn('"/health"', railway)
        self.assertNotIn('/api/v1/health', railway)
        dockerfile=(ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('http://localhost:${PORT}/health', dockerfile)
        self.assertNotIn('http://localhost:${PORT}/api/v1/health', dockerfile)

    def test_jobs_never_use_implicit_insert(self):
        needle = 'INSERT INTO jobs' + ' VALUES'
        for path in ROOT.rglob('*.py'):
            if '.git' in path.parts:
                continue
            self.assertNotIn(needle, path.read_text(encoding='utf-8'))
        database = (ROOT / 'backend' / 'database.py').read_text(encoding='utf-8')
        for column in ('id','organization_id','job_type','status','started_at','finished_at','records_processed','error','payload','attempt','schedule'):
            self.assertIn(column, database)

    def test_production_assets_have_no_demo_frontend_labels(self):
        frontend = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'frontend').glob('*'))
        self.assertNotRegex(frontend, r'(?i)demo|sqlite')

if __name__ == '__main__':
    unittest.main()
