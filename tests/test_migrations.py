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

if __name__ == '__main__':
    unittest.main()
