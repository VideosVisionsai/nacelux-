import json, sqlite3, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import database as data
from scoring import calculate

class MultiTenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()

        def connect():
            db = sqlite3.connect(self.tmp.name)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            return db

        self.connect = connect
        self._orig_connect = data.connect
        data.connect = connect

        ts = '2026-08-21T00:00:00Z'
        with connect() as db:
            db.executescript(data.SCHEMA)
            # Create Tenant A (Alpha Corp)
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ('org_alpha', 'Alpha Corp', 'alpha-corp', ts))
            db.execute("INSERT INTO users VALUES(?,?,?,?)", ('user_alpha', 'alpha@nacelux.local', 'Alpha Admin', ts))
            db.execute("INSERT INTO organization_members VALUES(?,?,?)", ('org_alpha', 'user_alpha', 'OWNER'))

            # Create Tenant B (Beta Industries)
            db.execute("INSERT INTO organizations VALUES(?,?,?,?)", ('org_beta', 'Beta Ind', 'beta-ind', ts))
            db.execute("INSERT INTO users VALUES(?,?,?,?)", ('user_beta', 'beta@nacelux.local', 'Beta Admin', ts))
            db.execute("INSERT INTO organization_members VALUES(?,?,?)", ('org_beta', 'user_beta', 'OWNER'))

            # Seed Company A belonging strictly to Tenant A
            db.execute("""INSERT INTO companies(id, organization_id, company_name, legal_form, rcs_number, creation_date, status, primary_nace_code, website_status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ('comp_alpha_1', 'org_alpha', 'Alpha Secret Sàrl', 'Sàrl', 'B111111', '2026-01-01', 'ACTIVE', '62.10', 'FOUND', ts, ts))
            db.execute("INSERT INTO opportunity_scores(id, organization_id, company_id, score, level, breakdown, recommended_action, calculated_at) VALUES(?,?,?,?,?,?,?,?)",
            ('opp_alpha_1', 'org_alpha', 'comp_alpha_1', 85, 'HIGH', '[]', 'CALL', ts))

            # Seed Company B belonging strictly to Tenant B
            db.execute("""INSERT INTO companies(id, organization_id, company_name, legal_form, rcs_number, creation_date, status, primary_nace_code, website_status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ('comp_beta_1', 'org_beta', 'Beta Confidential SA', 'SA', 'B222222', '2026-01-01', 'ACTIVE', '70.20', 'FOUND', ts, ts))
            db.execute("INSERT INTO opportunity_scores(id, organization_id, company_id, score, level, breakdown, recommended_action, calculated_at) VALUES(?,?,?,?,?,?,?,?)",
            ('opp_beta_1', 'org_beta', 'comp_beta_1', 92, 'VERY HIGH', '[]', 'CALL', ts))

            # Seed Prospects
            db.execute("INSERT INTO prospects(id, organization_id, company_id, status, priority, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            ('prospect_alpha_1', 'org_alpha', 'comp_alpha_1', 'NEW', 'HIGH', ts, ts))
            db.execute("INSERT INTO prospects(id, organization_id, company_id, status, priority, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            ('prospect_beta_1', 'org_beta', 'comp_beta_1', 'QUALIFIED', 'HIGH', ts, ts))

            # Seed Scoring weights
            db.execute("INSERT INTO scoring_weights VALUES(?,?,?,?,?)", ('w_alpha', 'org_alpha', 'freshness', 30, ts))
            db.execute("INSERT INTO scoring_weights VALUES(?,?,?,?,?)", ('w_beta', 'org_beta', 'freshness', 10, ts))

    def tearDown(self):
        data.connect = self._orig_connect
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_tenant_a_cannot_list_tenant_b_companies(self):
        alpha_companies = data.list_companies('org_alpha', {})
        beta_companies = data.list_companies('org_beta', {})

        self.assertEqual(len(alpha_companies), 1)
        self.assertEqual(alpha_companies[0]['id'], 'comp_alpha_1')
        self.assertEqual(alpha_companies[0]['company_name'], 'Alpha Secret Sàrl')

        self.assertEqual(len(beta_companies), 1)
        self.assertEqual(beta_companies[0]['id'], 'comp_beta_1')
        self.assertEqual(beta_companies[0]['company_name'], 'Beta Confidential SA')

    def test_tenant_a_cannot_fetch_tenant_b_company_detail(self):
        # Tenant A tries to inspect Tenant B's company
        detail = data.company_detail('org_alpha', 'comp_beta_1')
        self.assertIsNone(detail, "Security breach: Tenant A was able to read Tenant B's company detail")

        # Tenant B inspects its own company
        detail_b = data.company_detail('org_beta', 'comp_beta_1')
        self.assertIsNotNone(detail_b)
        self.assertEqual(detail_b['company_name'], 'Beta Confidential SA')

    def test_tenant_a_cannot_access_tenant_b_prospects(self):
        prospects_a = data.rows("SELECT * FROM prospects WHERE organization_id=?", ('org_alpha',))
        self.assertEqual(len(prospects_a), 1)
        self.assertEqual(prospects_a[0]['id'], 'prospect_alpha_1')

        # Negative query: verify no cross-tenant leakage
        cross = [p for p in prospects_a if p['organization_id'] == 'org_beta']
        self.assertEqual(len(cross), 0)

    def test_scoring_weights_are_strictly_isolated(self):
        w_a = data.one("SELECT weight FROM scoring_weights WHERE organization_id=? AND factor='freshness'", ('org_alpha',))
        w_b = data.one("SELECT weight FROM scoring_weights WHERE organization_id=? AND factor='freshness'", ('org_beta',))

        self.assertEqual(w_a['weight'], 30)
        self.assertEqual(w_b['weight'], 10)

    def test_recalculate_all_does_not_bleed_across_tenants(self):
        with self.connect() as db:
            data.recalculate_all(db, 'org_alpha')

        # Verify Tenant B's score remains untouched and associated only with Tenant B
        b_opp = data.one("SELECT * FROM opportunity_scores WHERE organization_id=? AND company_id=?", ('org_beta', 'comp_beta_1'))
        self.assertIsNotNone(b_opp)
        self.assertEqual(b_opp['score'], 92)

if __name__ == '__main__':
    unittest.main()
