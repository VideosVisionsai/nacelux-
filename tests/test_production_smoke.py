import json, os, sqlite3, sys, tempfile, unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import urlopen, Request
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

import app
import database as data
from scoring import calculate, MODEL_VERSION
from worker import Worker

class ProductionSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data.init_db()
        cls.server = HTTPServer(('127.0.0.1', 0), app.API)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_full_production_lifecycle_and_tenant_isolation(self):
        # 1. Health & Readiness Probe
        req_health = Request(f"http://127.0.0.1:{self.port}/api/v1/health")
        with urlopen(req_health, timeout=5) as res:
            self.assertEqual(res.status, 200)
            health_data = json.loads(res.read().decode())
            self.assertEqual(health_data.get('status'), 'HEALTHY')
            self.assertEqual(health_data.get('version'), '2.1')
            self.assertEqual(health_data.get('database', {}).get('status'), 'LOCAL_FALLBACK')

        # 2. Workspace Setup (Tenant 1: Lux Prime Tech)
        org1_id = "org_smoke_lux_prime"
        user1_id = "user_smoke_alice"
        ts = data.now()
        with data.connect() as db:
            db.execute("INSERT OR REPLACE INTO organizations(id, name, slug, created_at) VALUES(?,?,?,?)",
                       (org1_id, "Lux Prime Tech", "lux-prime-tech", ts))
            db.execute("INSERT OR REPLACE INTO users(id, email, display_name, created_at) VALUES(?,?,?,?)",
                       (user1_id, "alice@luxprime.lu", "Alice Prime", ts))
            db.execute("INSERT OR REPLACE INTO organization_members(organization_id, user_id, role) VALUES(?,?,?)",
                       (org1_id, user1_id, "OWNER"))

        # 3. Create Company under Tenant 1
        comp1_id = "comp_smoke_001"
        with data.connect() as db:
            db.execute("""INSERT OR REPLACE INTO companies(
                id, organization_id, company_name, legal_form, rcs_number, creation_date, status,
                primary_nace_code, category, niche, municipality, website_status, digital_score,
                seo_opportunity, google_status, decision_maker_status, niche_attractiveness,
                commercial_potential, source_status, source_name, is_demo, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (comp1_id, org1_id, "Lux AI Systems Sàrl", "Sàrl", "B888001", "2026-06-01", "ACTIVE",
             "62.10", "Technology", "Software Development", "Esch-sur-Alzette", "NOT_FOUND", 15,
             85, "NOT_FOUND", "FOUND", 95, 90, "OFFICIAL", "RESA-2026_231", 0, ts, ts))

        # 4. Run Opportunity Scoring & Verify Provenance
        with data.connect() as db:
            data.recalculate_all(db, org1_id)

        detail1 = data.company_detail(org1_id, comp1_id)
        self.assertIsNotNone(detail1)
        self.assertGreaterEqual(detail1['opportunity_score'], 85)
        self.assertEqual(detail1['opportunity_level'], 'HIGH')
        self.assertIn('scoring_provenance', detail1)
        prov = detail1['scoring_provenance']
        self.assertIsNotNone(prov)
        self.assertEqual(prov['model_version'], MODEL_VERSION)
        self.assertTrue(len(prov['provenance_fingerprint']) == 64)
        self.assertEqual(prov['input_snapshot']['website_status'], 'NOT_FOUND')

        # 5. Create Prospect & Verify Audit Trail
        prospect_id = "prospect_smoke_001"
        with data.connect() as db:
            db.execute("INSERT OR REPLACE INTO prospects(id, organization_id, company_id, status, priority, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                       (prospect_id, org1_id, comp1_id, "QUALIFIED", "HIGH", ts, ts))
        data.audit(org1_id, "QUALIFY_PROSPECT", "company", comp1_id, {"prospect_id": prospect_id})

        logs = data.rows("SELECT * FROM audit_logs WHERE organization_id=? AND entity_id=?", (org1_id, comp1_id))
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]['action'], 'QUALIFY_PROSPECT')

        # 6. Verify Background Worker Execution for Tenant 1
        job_id = "job_smoke_recalc"
        with data.connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs(id, organization_id, job_type, status, started_at, payload) VALUES(?,?,?,?,?,?)",
                       (job_id, org1_id, "OPPORTUNITY_RECALCULATION", "QUEUED", ts, "{}"))

        worker = Worker(data.connect)
        processed = worker.process_queued_jobs(limit=10)
        self.assertEqual(processed, 1)

        job_row = data.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        self.assertEqual(job_row['status'], 'SUCCESS')
        self.assertIsNotNone(job_row['finished_at'])

        # 7. MULTI-TENANT ISOLATION PROOF: Tenant 2 (Nordic Capital)
        org2_id = "org_smoke_nordic"
        user2_id = "user_smoke_bob"
        with data.connect() as db:
            db.execute("INSERT OR REPLACE INTO organizations(id, name, slug, created_at) VALUES(?,?,?,?)",
                       (org2_id, "Nordic Capital", "nordic-capital", ts))
            db.execute("INSERT OR REPLACE INTO users(id, email, display_name, created_at) VALUES(?,?,?,?)",
                       (user2_id, "bob@nordic.lu", "Bob Nordic", ts))
            db.execute("INSERT OR REPLACE INTO organization_members(organization_id, user_id, role) VALUES(?,?,?)",
                       (org2_id, user2_id, "OWNER"))

        # Tenant 2 cannot list Tenant 1's companies
        org2_companies = data.list_companies(org2_id, {})
        self.assertEqual(len(org2_companies), 0, "Leakage: Tenant 2 was able to view Tenant 1's companies")

        # Tenant 2 cannot view Tenant 1's company detail
        detail_unauthorized = data.company_detail(org2_id, comp1_id)
        self.assertIsNone(detail_unauthorized, "Leakage: Tenant 2 accessed Tenant 1's company detail")

        # Tenant 2 cannot view Tenant 1's prospects
        org2_prospects = data.rows("SELECT * FROM prospects WHERE organization_id=?", (org2_id,))
        self.assertEqual(len(org2_prospects), 0, "Leakage: Tenant 2 accessed Tenant 1's prospects")

        # Tenant 2 cannot view Tenant 1's audit logs
        org2_logs = data.rows("SELECT * FROM audit_logs WHERE organization_id=?", (org2_id,))
        self.assertEqual(len(org2_logs), 0, "Leakage: Tenant 2 accessed Tenant 1's audit logs")

if __name__ == '__main__':
    unittest.main()
