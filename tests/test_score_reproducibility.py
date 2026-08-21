import json, sqlite3, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import database as data
from scoring import calculate, MODEL_VERSION

class ScoreReproducibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()

        def connect():
            db = sqlite3.connect(self.tmp.name)
            db.row_factory = sqlite3.Row
            return db

        self.connect = connect
        self._orig_connect = data.connect
        data.connect = connect

        ts = '2026-08-21T00:00:00Z'
        with connect() as db:
            db.executescript(data.SCHEMA)
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ('org_repro_test', 'Repro Workspace', 'repro-ws', ts))
            db.execute("INSERT INTO users VALUES(?,?,?,?)", ('user_repro', 'repro@nacelux.local', 'Repro User', ts))
            db.execute("INSERT INTO organization_members VALUES(?,?,?)", ('org_repro_test', 'user_repro', 'OWNER'))

            db.execute("""INSERT INTO companies(id, organization_id, company_name, legal_form, rcs_number, creation_date, status, primary_nace_code, website_status, digital_score, seo_opportunity, google_status, decision_maker_status, niche_attractiveness, commercial_potential, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('comp_repro_1', 'org_repro_test', 'Repro Labs Sàrl', 'Sàrl', 'B999999', '2026-07-01', 'ACTIVE', '62.10', 'NOT_FOUND', 10, 80, 'NOT_FOUND', 'FOUND', 90, 85, ts, ts))

    def tearDown(self):
        data.connect = self._orig_connect
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_score_is_deterministic_and_reproducible(self):
        company = {
            'creation_date': '2026-07-01',
            'website_status': 'NOT_FOUND',
            'digital_score': 10,
            'seo_opportunity': 80,
            'google_status': 'NOT_FOUND',
            'decision_maker_status': 'FOUND',
            'niche_attractiveness': 90,
            'commercial_potential': 85
        }
        res1 = calculate(company)
        res2 = calculate(company)

        self.assertEqual(res1['score'], res2['score'])
        self.assertEqual(res1['level'], res2['level'])
        self.assertEqual(res1['provenance_fingerprint'], res2['provenance_fingerprint'])
        self.assertEqual(res1['model_version'], MODEL_VERSION)

    def test_fingerprint_changes_if_inputs_change(self):
        company1 = {'creation_date': '2026-07-01', 'website_status': 'NOT_FOUND'}
        company2 = {'creation_date': '2026-07-01', 'website_status': 'FOUND', 'digital_score': 80}

        res1 = calculate(company1)
        res2 = calculate(company2)

        self.assertNotEqual(res1['provenance_fingerprint'], res2['provenance_fingerprint'])

    def test_reproduction_from_saved_input_snapshot(self):
        company = {
            'creation_date': '2026-06-15',
            'website_status': 'NOT_FOUND',
            'seo_opportunity': 90,
            'google_status': 'NOT_FOUND',
            'decision_maker_status': 'FOUND',
            'niche_attractiveness': 95,
            'commercial_potential': 90
        }
        original = calculate(company)
        snapshot = original['input_snapshot']

        # Re-execute purely from snapshot
        reconstructed = calculate(snapshot, weights=snapshot['weights'])
        self.assertEqual(reconstructed['score'], original['score'])
        self.assertEqual(reconstructed['provenance_fingerprint'], original['provenance_fingerprint'])

    def test_database_persists_and_restores_provenance(self):
        with self.connect() as db:
            data.recalculate_all(db, 'org_repro_test')

        detail = data.company_detail('org_repro_test', 'comp_repro_1')
        self.assertIsNotNone(detail)
        self.assertIn('scoring_provenance', detail)
        prov = detail['scoring_provenance']
        self.assertIsNotNone(prov)
        self.assertEqual(prov['model_version'], MODEL_VERSION)
        self.assertIsNotNone(prov['provenance_fingerprint'])
        self.assertIsInstance(detail['breakdown'], list)

if __name__ == '__main__':
    unittest.main()
